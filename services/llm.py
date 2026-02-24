import httpx
from config import settings


async def ask_llm(messages: list, temperature: float = 0.1, max_tokens: int = 2000):

    if settings.llm_provider == "deepseek":
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.deepseek_api_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                json={
                    "model": settings.chat_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # ---------- OPENAI ----------
    elif settings.llm_provider == "openai":
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.openai_api_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.chat_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )

        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    else:
        raise Exception("Unknown LLM provider")
