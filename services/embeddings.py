import httpx
import asyncio
import PyPDF2
import random
from io import BytesIO
from typing import List, Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential
from sentence_transformers import SentenceTransformer
import numpy as np

from config import settings
from services.supabase import supabase
from core.logger import logger

# Глобальная переменная для модели (загружается один раз при первом вызове)
_model = None

def get_model():
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model: all-MiniLM-L6-v2")
        _model = SentenceTransformer('all-MiniLM-L6-v2')
        logger.info("Model loaded successfully")
    return _model

async def get_embedding(text: str) -> List[float]:
    """Получение эмбеддинга через локальную sentence-transformers модель"""
    try:
        model = get_model()
        # Выполняем encode в отдельном потоке, чтобы не блокировать asyncio
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(None, lambda: model.encode(text).tolist())
        return embedding
    except Exception as e:
        logger.error(f"Error generating embedding: {e}", exc_info=True)
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
    """
    Полный цикл обработки документа:
    - извлечение текста
    - чанкинг
    - генерация эмбеддингов
    - сохранение в Supabase
    """
    try:
        # 1. Извлечение текста
        logger.info(f"process_document: начало, файл {file.filename}")
        text = await extract_text_from_file(file)
        if not text.strip():
            logger.warning(f"Файл {file.filename} не содержит текста")
            return 0
        logger.info(f"Извлечён текст длиной {len(text)} символов")
        
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
            tasks.append(_save_chunk_safe(chunk, chunk_metadata))
        
        # Выполняем все задачи, даже если некоторые упадут
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Считаем успешные
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
    """Безопасное сохранение одного чанка с эмбеддингом"""
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