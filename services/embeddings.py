import httpx
import asyncio
import PyPDF2
from io import BytesIO
from typing import List, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential
from openai import OpenAI

from config import settings
from services.supabase import supabase
from core.logger import logger

# Инициализация клиента OpenAI
client = OpenAI(api_key=settings.openai_api_key)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def get_embedding(text: str) -> List[float]:
    """Получение эмбеддинга через OpenAI API"""
    try:
        logger.info(f"Requesting embedding from OpenAI for text length {len(text)}")
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
            encoding_format="float"
        )
        embedding = response.data[0].embedding
        logger.info(f"Received embedding with {len(embedding)} dimensions")
        return embedding
    except Exception as e:
        logger.error(f"OpenAI API error: {e}", exc_info=True)
        raise

def split_text(text: str, chunk_size: int = None, overlap: int = None) -> List[str]:
    """Разделение текста на чанки с перекрытием"""
    if chunk_size is None:
        chunk_size = settings.chunk_size
    if overlap is None:
        overlap = settings.chunk_overlap
    
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        end = min(start + chunk_size, text_length)
        if end < text_length:
            last_period = text.rfind('.', start, end)
            last_space = text.rfind(' ', start, end)
            cut_point = max(last_period, last_space)
            if cut_point > start:
                end = cut_point + 1
        chunks.append(text[start:end].strip())
        start = end - overlap if end < text_length else text_length
    
    return chunks

async def extract_text_from_file(file) -> str:
    """Извлечение текста из загруженного файла"""
    content = await file.read()
    
    if file.filename.endswith('.txt'):
        return content.decode('utf-8')
    elif file.filename.endswith('.pdf'):
        pdf_reader = PyPDF2.PdfReader(BytesIO(content))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        return text
    else:
        raise ValueError(f"Unsupported file type: {file.filename}")

async def process_document(user_id: str, file, metadata: dict) -> int:
    try:
        logger.info(f"process_document: начало, файл {file.filename}")
        text = await extract_text_from_file(file)
        if not text.strip():
            logger.warning(f"Файл {file.filename} не содержит текста")
            return 0
        logger.info(f"Извлечён текст длиной {len(text)} символов")
        
        chunks = split_text(text)
        logger.info(f"Файл {file.filename} разбит на {len(chunks)} чанков")
        
        doc_metadata = {
            "user_id": user_id,
            "filename": file.filename,
            "content_type": file.content_type,
            **metadata
        }
        
        tasks = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = {
                **doc_metadata,
                "chunk_index": i,
                "chunk_size": len(chunk)
            }
            tasks.append(_save_chunk_safe(chunk, chunk_metadata))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = 0
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(f"Ошибка при сохранении чанка {i} файла {file.filename}: {res}")
            else:
                success_count += 1
        
        logger.info(f"Успешно сохранено {success_count} из {len(chunks)} чанков для {file.filename}")
        return success_count
        
    except Exception as e:
        logger.error(f"Критическая ошибка при обработке {file.filename}: {e}", exc_info=True)
        raise

async def _save_chunk_safe(content: str, metadata: dict):
    try:
        embedding = await get_embedding(content)
        data = {
            "content": content,
            "metadata": metadata,
            "embedding": embedding
        }
        result = supabase.table("documents").insert(data).execute()
        return result.data[0]["id"]
    except Exception as e:
        logger.error(f"Ошибка в _save_chunk для чанка: {e}", exc_info=True)
        raise