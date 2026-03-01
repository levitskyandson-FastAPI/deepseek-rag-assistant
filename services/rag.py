import json
import numpy as np
from typing import List, Dict, Any, Optional
from services.db import get_db_pool
from services.embeddings import get_embedding
from core.logger import logger
from config import settings

async def retrieve_relevant_docs(
    query: str,
    user_id: Optional[str] = None,
    top_k: int = 5,
    threshold: float = 0.1,
) -> List[Dict[str, Any]]:
    """
    Поиск релевантных документов по косинусному сходству.
    Эмбеддинги хранятся в текстовом виде, вычисления производятся в Python.
    """
    try:
        # Получаем эмбеддинг запроса через YandexGPT
        query_embedding = await get_embedding(query)
        if not query_embedding:
            logger.warning("RAG: не удалось получить эмбеддинг запроса")
            return []

        # Загружаем все документы клиента с эмбеддингами
        pool = get_db_pool()
        async with pool.acquire() as conn:
            if user_id:
                rows = await conn.fetch("""
                    SELECT id, content, metadata, embedding
                    FROM documents
                    WHERE client_id = $1 AND embedding IS NOT NULL
                """, user_id)
            else:
                rows = await conn.fetch("""
                    SELECT id, content, metadata, embedding
                    FROM documents
                    WHERE embedding IS NOT NULL
                """)

        if not rows:
            logger.info("RAG: нет документов с эмбеддингами")
            return []

        # Преобразуем эмбеддинги из текста в numpy массивы
        docs = []
        for row in rows:
            try:
                emb_list = json.loads(row['embedding'])
                if not isinstance(emb_list, list):
                    continue
                emb_array = np.array(emb_list, dtype=np.float32)
                docs.append({
                    'id': row['id'],
                    'content': row['content'],
                    'metadata': row['metadata'],
                    'embedding': emb_array
                })
            except Exception as e:
                logger.warning(f"Ошибка парсинга эмбеддинга документа {row['id']}: {e}")

        if not docs:
            return []

        # Вычисляем косинусное сходство
        query_array = np.array(query_embedding, dtype=np.float32)
        # Нормализуем векторы (косинусное сходство = скалярное произведение нормализованных векторов)
        query_norm = query_array / np.linalg.norm(query_array)
        for doc in docs:
            doc_norm = doc['embedding'] / np.linalg.norm(doc['embedding'])
            similarity = np.dot(query_norm, doc_norm)
            doc['score'] = float(similarity)  # от -1 до 1, чем ближе к 1, тем лучше

        # Сортируем по убыванию сходства и фильтруем по порогу
        sorted_docs = sorted(docs, key=lambda x: x['score'], reverse=True)
        results = [doc for doc in sorted_docs if doc['score'] >= threshold][:top_k]

        logger.info(f"📚 RAG найдено документов: {len(results)}")
        return results

    except Exception as e:
        logger.exception(f"RAG retrieve error: {e}")
        return []