import httpx
import json
from typing import Tuple, List, Optional
from config import settings
from services.rag import retrieve_relevant_docs
from core.logger import logger

async def ask_deepseek(messages: list, temperature: float = 0.1, max_tokens: int = 2000) -> str:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.deepseek_api_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json={
                "model": settings.chat_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
        )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

async def ask_with_rag(
    user_message: str,
    user_id: Optional[str] = None,
    use_rag: bool = True,
    system_extra: Optional[str] = None,
    context_info: Optional[str] = None
) -> Tuple[str, List[str]]:
    sources = []
    
    # Базовая системная инструкция
    base_system = "Ты — корпоративный ИИ-ассистент агентства Levitsky & Son AI Solutions."

    # Если есть дополнительные инструкции, добавляем
    extra = system_extra if system_extra else ""

    # Если есть информация о состоянии, добавляем
    context = f"Текущий контекст диалога: {context_info}" if context_info else ""

    if use_rag:
        docs = await retrieve_relevant_docs(user_message, user_id)
        logger.info(f"📊 RAG: найдено документов: {len(docs)}")
        if docs:
            context_docs = "\n\n".join([doc["content"] for doc in docs])
            sources = [doc["metadata"].get("filename", "unknown") for doc in docs]
            system_prompt = f"""{base_system}
{extra}
{context}

Отвечай на вопросы, используя информацию из документов ниже. Если в документах нет ответа, скажи: «У меня нет информации».

Документы:
{context_docs}"""
        else:
            system_prompt = f"""{base_system}
{extra}
{context}
Если у тебя нет информации, честно скажи об этом."""
    else:
        system_prompt = f"""{base_system}
{extra}
{context}
Ты — полезный ИИ-ассистент, отвечай дружелюбно."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    reply = await ask_deepseek(messages)
    return reply, sources