from fastapi import APIRouter, HTTPException
from models.schemas import ChatRequest, ChatResponse
from services.deepseek import ask_with_rag
from core.logger import logger

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.post("/", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    try:
        reply, sources = await ask_with_rag(
            user_message=request.message,
            user_id=request.user_id,
            use_rag=request.use_rag,
            system_extra=request.system_extra,
            context_info=request.context_info
        )
        return ChatResponse(reply=reply, sources=sources)
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))