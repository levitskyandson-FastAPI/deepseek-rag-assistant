from services.supabase import supabase
from services.embeddings import get_embedding
from typing import List, Dict, Any, Optional
from core.logger import logger


async def retrieve_relevant_docs(
    query: str,
    user_id: Optional[str] = None,
    top_k: int = 5,
    threshold: float = 0.1,
) -> List[Dict[str, Any]]:

    try:
        query_embedding = await get_embedding(query)

        params = {
            "query_embedding": query_embedding,
            "match_threshold": threshold,
            "match_count": top_k,
        }

        if user_id:
            params["filter_user_id"] = user_id

        result = supabase.rpc("match_documents", params).execute()

        # 🛡️ Безопасная проверка
        if not result or not hasattr(result, "data"):
            logger.warning("RAG: result has no data")
            return []

        if not isinstance(result.data, list):
            logger.warning(f"RAG: unexpected data format: {result.data}")
            return []

        logger.info(f"📚 RAG найдено документов: {len(result.data)}")

        return result.data or []

    except Exception as e:
        logger.exception("RAG retrieve error")
        return []