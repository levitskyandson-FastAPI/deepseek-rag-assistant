import httpx
from typing import Tuple, List, Optional
from config import settings
from services.rag import retrieve_relevant_docs
from core.logger import logger

async def ask_deepseek(messages: list, temperature: float = 0.1, max_tokens: int = 2000) -> str:
    """Базовый вызов DeepSeek Chat API"""
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
    use_rag: bool = True
) -> Tuple[str, List[str]]:
    """
    Получить ответ от DeepSeek с подгрузкой контекста из RAG.
    Возвращает (ответ, список источников).
    """
    sources = []
    
    if use_rag:
        logger.info(f"🔍 RAG: поиск для user_id={user_id}, сообщение='{user_message}'")
        docs = await retrieve_relevant_docs(user_message, user_id)
        logger.info(f"📊 RAG: найдено документов: {len(docs)}")
        
        if docs:
            context = "\n\n".join([doc["content"] for doc in docs])
            sources = [doc["metadata"].get("filename", "unknown") for doc in docs]
            system_prompt = f"""Ты — корпоративный ИИ-ассистент агентства Levitsky & Son AI Solutions.
Отвечай на вопросы, используя информацию из документов ниже. Не упоминай, что ответ основан на документах, просто давай чёткий ответ.
Если в документах нет ответа, скажи: «У меня нет информации по данному вопросу.»
Не придумывай факты.
Если клиент интересуется услугами, ценами, сроками, кейсами или просит помощи, после ответа обязательно предложи ему бесплатную консультацию. Например: «Если хотите обсудить детали с нашим специалистом, оставьте ваш номер телефона, и мы свяжемся с вами в ближайшее время.»
Будь дружелюбным, но профессиональным.

Документы:
{context}"""
        else:
            system_prompt = "Ты — корпоративный ИИ-ассистент агентства Levitsky & Son AI Solutions. Если у тебя нет информации, честно скажи об этом. Если клиент спрашивает об услугах, предложи консультацию."
    else:
        system_prompt = "Ты — полезный ИИ-ассистент."
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    reply = await ask_deepseek(messages)
    return reply, sources