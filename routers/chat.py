from fastapi import APIRouter, HTTPException
from models.schemas import ChatRequest, ChatResponse
from services.deepseek import ask_with_rag
from core.logger import logger

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.post("/", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    return ChatResponse(
        reply="CHAT ENDPOINT WORKS",
        sources=[]
    )