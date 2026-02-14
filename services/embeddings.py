@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def get_embedding(text: str) -> List[float]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.deepseek_api_url}/embeddings",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json={
                "input": text,
                "model": settings.embedding_model
            }
        )
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error(f"DeepSeek API error: статус {e.response.status_code}, тело: {e.response.text}")
        raise
    return resp.json()["data"][0]["embedding"]