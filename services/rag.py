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
    logger.info(f"🔍 RAG retrieve_relevant_docs: query='{query[:100]}...', user_id={user_id}, top_k={top_k}, threshold={threshold}")
    try:
        query_embedding = await get_embedding(query)
        logger.info(f"📊 Получен эмбеддинг запроса, длина: {len(query_embedding)}, первые 5: {query_embedding[:5]}")
        if not query_embedding:
            logger.warning("RAG: не удалось получить эмбеддинг запроса")
            return []

        pool = get_db_pool()
        async with pool.acquire() as conn:
            if user_id:
                rows = await conn.fetch("""
                    SELECT id, content, metadata, embedding
                    FROM documents
                    WHERE client_id = $1 AND embedding IS NOT NULL
                """, user_id)
                logger.info(f"📚 Найдено документов в БД для клиента {user_id}: {len(rows)}")
            else:
                rows = await conn.fetch("""
                    SELECT id, content, metadata, embedding
                    FROM documents
                    WHERE embedding IS NOT NULL
                """)
                logger.info(f"📚 Найдено документов (всех) в БД: {len(rows)}")

        if not rows:
            logger.info("RAG: нет документов с эмбеддингами")
            return []

        docs = []
        for row in rows:
            try:
                embedding = row['embedding']
                if embedding is None:
                    continue
                # Если это уже numpy array, преобразуем в массив для вычислений
                # pgvector может вернуть как list, так и numpy.ndarray
                emb_array = np.array(embedding, dtype=np.float32)
                
                # Обработка метаданных (могут быть строкой или словарём)
                metadata = row['metadata']
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except:
                        metadata = {}
                elif not isinstance(metadata, dict):
                    metadata = {}

                docs.append({
                    'id': row['id'],
                    'content': row['content'],
                    'metadata': metadata,
                    'embedding': emb_array
                })
            except Exception as e:
                logger.warning(f"Ошибка обработки документа {row['id']}: {e}", exc_info=True)
                continue

        if not docs:
            logger.info("RAG: нет документов после обработки")
            return []

        query_array = np.array(query_embedding, dtype=np.float32)
        query_norm = query_array / np.linalg.norm(query_array)
        for doc in docs:
            doc_norm = doc['embedding'] / np.linalg.norm(doc['embedding'])
            similarity = np.dot(query_norm, doc_norm)
            doc['score'] = float(similarity)

        sorted_docs = sorted(docs, key=lambda x: x['score'], reverse=True)
        results = [doc for doc in sorted_docs if doc['score'] >= threshold][:top_k]

        logger.info(f"📚 RAG итоговых документов: {len(results)}")
        for i, doc in enumerate(results):
            logger.info(f"  {i+1}: id={doc['id']}, score={doc['score']:.4f}, filename={doc['metadata'].get('filename', 'unknown')}")
        return results

    except Exception as e:
        logger.exception(f"RAG retrieve error: {e}")
        return []