import httpx
import json
from typing import Tuple, List, Optional
from config import settings
from services.rag import retrieve_relevant_docs
from core.logger import logger


# ===============================
# DeepSeek API
# ===============================

async def ask_deepseek(
    messages: list,
    temperature: float = 0.1,
    max_tokens: int = 2000
) -> str:

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
            },
        )

    data = resp.json()

    logger.info(f"DeepSeek RAW: {data}")

    # 🔒 безопасный парсинг ответа
    if isinstance(data, dict):
        choices = data.get("choices")

        if choices and isinstance(choices, list):
            first = choices[0]

            # OpenAI-style формат
            if "message" in first:
                content = first["message"].get("content")
                if content:
                    return content

            # альтернативный формат
            if "text" in first:
                return first["text"]

    raise ValueError(f"Unexpected DeepSeek response: {data}")


# ===============================
# Universal SaaS RAG Logic
# ===============================

async def ask_with_rag(
    user_message: str,
    user_id: Optional[str] = None,
    use_rag: bool = True,
    system_extra: Optional[str] = None,
    context_info: Optional[str] = None
) -> Tuple[str, List[str]]:

    sources = []

    # 🟢 Универсальный системный промпт (НЕ захардкоженный бренд)
    base_system = "Ты — корпоративный ИИ-ассистент компании клиента."

    # ===============================
    # Обработка context_info
    # ===============================

    context_summary = ""
    greeted = False

    if context_info:
        try:
            ctx = json.loads(context_info)

            greeted = ctx.get("greeted", False)

            collected = ctx.get("collected", {})
            if collected:
                parts = []

                if collected.get("name"):
                    parts.append(f"имя клиента: {collected['name']}")

                if collected.get("company"):
                    parts.append(f"компания: {collected['company']}")

                if collected.get("preferred_date"):
                    parts.append(
                        f"договорились о консультации на {collected['preferred_date']}"
                    )

                if parts:
                    context_summary = (
                        "Краткая информация о диалоге: "
                        + ", ".join(parts)
                        + "."
                    )

        except Exception as e:
            logger.error(f"Ошибка парсинга context_info: {e}")

    # ===============================
    # Логика приветствия
    # ===============================

    if greeted:
        greeting_instruction = (
            "Не здоровайся повторно, просто продолжай диалог."
        )
    else:
        greeting_instruction = (
            "Ты начинаешь разговор, можешь поприветствовать клиента."
        )

    extra = system_extra.strip() if system_extra else ""

    full_extra = f"{greeting_instruction}\n{extra}".strip()

    if context_summary:
        full_extra += f"\n\n{context_summary}"

    full_system_block = f"{base_system}\n{full_extra}".strip()

    # ===============================
    # RAG
    # ===============================

    if use_rag:
        docs = await retrieve_relevant_docs(user_message, user_id)

        logger.info(f"📊 RAG: найдено документов: {len(docs)}")

        if docs:
            context_docs = "\n\n".join(
                [doc.get("content", "") for doc in docs]
            )

            sources = [
                doc.get("metadata", {}).get("filename", "unknown")
                for doc in docs
            ]

            system_prompt = f"""{full_system_block}

Отвечай, используя информацию из документов ниже.
Если ответа в документах нет — честно скажи об этом.

Документы:
{context_docs}
"""
        else:
            system_prompt = f"""{full_system_block}

Если информации нет — честно скажи об этом.
"""
    else:
        system_prompt = f"""{full_system_block}

Ты — полезный ИИ-ассистент. Отвечай дружелюбно.
"""

    # ===============================
    # Формирование запроса к LLM
    # ===============================

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    reply = await ask_deepseek(messages)

    return reply, sources