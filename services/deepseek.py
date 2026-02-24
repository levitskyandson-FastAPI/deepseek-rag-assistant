import httpx
import json
from typing import Tuple, List, Optional
from config import settings
from services.rag import retrieve_relevant_docs
from core.logger import logger

async def ask_deepseek(messages: list, temperature: float = 0.1, max_tokens: int = 2000) -> str:
    logger.info("ASK_DEEPSEEK CALLED")
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.deepseek_api_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.chat_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )

    data = resp.json()

    # Логируем сырой ответ
    logger.info(f"DeepSeek RAW response: {data}")

    # Защитный парсинг
    if "choices" in data and len(data["choices"]) > 0:
        choice = data["choices"][0]

        # формат OpenAI-совместимый
        if "message" in choice and "content" in choice["message"]:
            return choice["message"]["content"]

        # иногда DeepSeek возвращает text
        if "text" in choice:
            logger.info(f"DEEPSEEK RESPONSE STRUCTURE: {data}")
            return choice["text"]

    raise ValueError(f"Unexpected DeepSeek response format: {data}")

async def ask_with_rag(
    user_message: str,
    user_id: Optional[str] = None,
    use_rag: bool = True,
    system_extra: Optional[str] = None,
    context_info: Optional[str] = None
) -> Tuple[str, List[str]]:
    sources = []
    base_system = "Ты — корпоративный ИИ-ассистент агентства Levitsky & Son AI Solutions."

    # --- НОВЫЙ БЛОК: формируем сводку из context_info ---
    context_summary = ""
    if context_info:
        try:
            ctx = json.loads(context_info)
            collected = ctx.get("collected", {})
            if collected:
                parts = []
                if collected.get("name"):
                    parts.append(f"имя клиента: {collected['name']}")
                if collected.get("company"):
                    parts.append(f"компания: {collected['company']}")
                if collected.get("preferred_date"):
                    parts.append(f"договорились о консультации на {collected['preferred_date']}")
                if parts:
                    context_summary = "Краткая информация о диалоге: " + ", ".join(parts) + "."
        except Exception as e:
            logger.error(f"Ошибка парсинга context_info: {e}")
    # -----------------------------------------------------

    # Инструкция о приветствии
    greeted = False
    if context_info:
        try:
            ctx = json.loads(context_info)
            greeted = ctx.get("greeted", False)
        except:
            pass

    greeting_instruction = ""
    if greeted:
        greeting_instruction = "Не здоровайся повторно, просто продолжай диалог и отвечай на вопрос."
    else:
        greeting_instruction = "Ты начинаешь разговор, можешь поприветствовать клиента."

    extra = system_extra if system_extra else ""
    full_extra = f"{greeting_instruction}\n{extra}".strip()

    # Добавляем сводку, если она есть
    if context_summary:
        full_extra += f"\n\n{context_summary}"

    if use_rag:
        docs = await retrieve_relevant_docs(user_message, user_id)
        logger.info(f"📊 RAG: найдено документов: {len(docs)}")
        if docs:
            context_docs = "\n\n".join([doc["content"] for doc in docs])
            sources = [doc["metadata"].get("filename", "unknown") for doc in docs]
            system_prompt = f"""{base_system}
{full_extra}

Отвечай на вопросы, используя информацию из документов ниже. Если в документах нет ответа, скажи: «У меня нет информации».

Документы:
{context_docs}"""
        else:
            system_prompt = f"""{base_system}
{full_extra}
Если у тебя нет информации, честно скажи об этом."""
    else:
        system_prompt = f"""{base_system}
{full_extra}
Ты — полезный ИИ-ассистент, отвечай дружелюбно."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    
    reply = await ask_deepseek(messages)
    return reply, sources