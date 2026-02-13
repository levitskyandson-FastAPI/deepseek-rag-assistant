import httpx
import asyncio
from config import settings
from services.supabase import supabase
from core.logger import logger
from tenacity import retry, stop_after_attempt, wait_exponential
from fastapi import UploadFile
import PyPDF2
from io import BytesIO
from typing import List

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def get_embedding(text: str) -> List[float]:
    """Получение эмбеддинга через DeepSeek API с повторными попытками"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.deepseek_api_url}/embeddings",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json={
                "input": text,
                "model": settings.embedding_model
            }
        )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]

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
        # Не режем посередине предложения (опционально)
        if end < text_length:
            last_period = text.rfind('.', start, end)
            last_space = text.rfind(' ', start, end)
            cut_point = max(last_period, last_space)
            if cut_point > start:
                end = cut_point + 1
        chunks.append(text[start:end].strip())
        start = end - overlap if end < text_length else text_length
    
    return chunks

async def extract_text_from_file(file: UploadFile) -> str:
    """Извлечение текста из загруженного файла (поддерживает .txt и .pdf)"""
    content = await file.read()
    
    if file.filename.endswith('.txt'):
        return content.decode('utf-8')
    
    elif file.filename.endswith('.pdf'):
        try:
            pdf_reader = PyPDF2.PdfReader(BytesIO(content))
            text = ""
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text
            return text
        except Exception as e:
            logger.error(f"Ошибка при чтении PDF {file.filename}: {e}")
            raise ValueError(f"Не удалось извлечь текст из PDF: {e}")
    
    else:
        raise ValueError(f"Неподдерживаемый тип файла: {file.filename}. Поддерживаются .txt и .pdf")

async def process_document(user_id: str, file: UploadFile, metadata: dict) -> int:
    """
    Полный цикл обработки документа:
    - извлечение текста
    - чанкинг
    - генерация эмбеддингов
    - сохранение в Supabase
    Возвращает количество успешно сохранённых чанков.
    """
    try:
        logger.info(f"Начало обработки файла: {file.filename} для пользователя {user_id}")
        
        # 1. Извлечение текста
        text = await extract_text_from_file(file)
        if not text.strip():
            logger.warning(f"Файл {file.filename} не содержит текста")
            return 0
        
        # 2. Чанкинг
        chunks = split_text(text)
        logger.info(f"Файл {file.filename} разбит на {len(chunks)} чанков")
        
        # 3. Метаданные документа
        doc_metadata = {
            "user_id": user_id,
            "filename": file.filename,
            "content_type": file.content_type,
            **metadata
        }
        
        # 4. Для каждого чанка генерируем эмбеддинг и сохраняем
        tasks = []
        for i, chunk in enumerate(chunks):
            chunk_metadata = {
                **doc_metadata,
                "chunk_index": i,
                "chunk_size": len(chunk)
            }
            tasks.append(_save_chunk_safe(chunk, chunk_metadata, i, file.filename))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 5. Подсчёт успешных
        success_count = 0
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(f"Ошибка при сохранении чанка {i} файла {file.filename}: {res}")
            else:
                success_count += 1
        
        logger.info(f"Файл {file.filename}: успешно сохранено {success_count} из {len(chunks)} чанков")
        return success_count
        
    except Exception as e:
        logger.error(f"Критическая ошибка при обработке {file.filename}: {e}", exc_info=True)
        raise  # пробрасываем для верхнего уровня

async def _save_chunk_safe(content: str, metadata: dict, chunk_index: int, filename: str):
    """Безопасное сохранение одного чанка с обработкой ошибок"""
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
        logger.error(f"Ошибка в _save_chunk для чанка {chunk_index} файла {filename}: {e}", exc_info=True)
        raise  # пробрасываем для gather