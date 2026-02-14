from services.supabase import supabase
from services.embeddings import get_embedding
from typing import List, Dict, Any, Optional
from core.logger import logger

async def retrieve_relevant_docs(
    query: str,
    user_id: Optional[str] = None,
    top_k: int = 5,
    threshold: float = 0.7
) -> List[Dict[str, Any]]:
    """
    Поиск релевантных документов по векторной близости.
    Возвращает список чанков с текстом и метаданными.
    """
    # Получаем эмбеддинг запроса
    query_embedding = await get_embedding(query)
    
    # Параметры для RPC вызова
    params = {
        "query_embedding": query_embedding,
        "match_threshold": threshold,
        "match_count": top_k
    }
    if user_id:
        params["filter_user_id"] = user_id
    
    try:
        result = supabase.rpc("match_documents", params).execute()
        logger.info(f"📚 retrieve_relevant_docs: запрос '{query}', user_id={user_id}, найдено {len(result.data)} документов")
        if result.data:
            for i, doc in enumerate(result.data):
                filename = doc.get("metadata", {}).get("filename", "unknown")
                similarity = doc.get("similarity", 0)
                logger.info(f"   - документ {i}: {filename}, сходство {similarity:.3f}")
        return result.data
    except Exception as e:
        logger.error(f"❌ Ошибка при поиске документов: {e}", exc_info=True)
        return []