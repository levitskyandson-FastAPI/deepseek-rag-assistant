from services.supabase import supabase
from services.embeddings import get_embedding
from typing import List, Dict, Any

async def retrieve_relevant_docs(
    query: str,
    user_id: str = None,
    top_k: int = 5,
    threshold: float = 0.7
) -> List[Dict[str, Any]]:
    query_embedding = await get_embedding(query)
    
    params = {
        "query_embedding": query_embedding,
        "match_threshold": threshold,
        "match_count": top_k
    }
    if user_id:
        params["filter_user_id"] = user_id
    
    result = supabase.rpc("match_documents", params).execute()
    return result.data