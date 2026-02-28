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
    Поиск релевантных документов по векторному сходству.
    Использует pgvector оператор <=> (косинусное расстояние).
    """
    try:
        # 1. Получаем эмбеддинг запроса через YandexGPT
        query_embedding = await get_embedding(query)
        if not query_embedding:
            logger.warning("RAG: не удалось получить эмбеддинг запроса")
            return []

        # Преобразуем список в строку для подстановки в SQL (формат PostgreSQL для vector)
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        pool = get_db_pool()
        async with pool.acquire() as conn:
            # Формируем запрос с фильтрацией по client_id (user_id)
            # Используем <=> для косинусного расстояния (чем меньше, тем ближе)
            if user_id:
                rows = await conn.fetch("""
                    SELECT id, content, metadata, (embedding <=> $1::vector) AS distance
                    FROM documents
                    WHERE client_id = $2 AND embedding IS NOT NULL
                    ORDER BY distance ASC
                    LIMIT $3
                """, embedding_str, user_id, top_k)
            else:
                rows = await conn.fetch("""
                    SELECT id, content, metadata, (embedding <=> $1::vector) AS distance
                    FROM documents
                    WHERE embedding IS NOT NULL
                    ORDER BY distance ASC
                    LIMIT $2
                """, embedding_str, top_k)

        # Преобразуем записи в словари и фильтруем по порогу
        results = []
        for row in rows:
            doc = dict(row)
            # distance <=> — косинусное расстояние (0 = идентичны, 2 = противоположны)
            # Нам нужно, чтобы расстояние было меньше порога (чем меньше, тем лучше)
            if doc['distance'] <= threshold:
                results.append(doc)

        logger.info(f"📚 RAG найдено документов: {len(results)} (всего кандидатов: {len(rows)})")
        return results

    except Exception as e:
        logger.exception(f"RAG retrieve error: {e}")
        return []