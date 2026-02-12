import pytest
from httpx import AsyncClient
from main import app

@pytest.mark.asyncio
async def test_chat_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/chat/", json={
            "user_id": "test_user",
            "message": "Привет, что ты умеешь?",
            "use_rag": False
        })
    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    assert isinstance(data["reply"], str)

@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"