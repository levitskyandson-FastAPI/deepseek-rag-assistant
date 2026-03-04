import httpx
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from urllib.parse import urlencode

from core.logger import logger
from services.db import get_db_pool
from config import settings

# Константы Avito API
AVITO_AUTH_URL = "https://api.avito.ru/oauth/authorize"
AVITO_TOKEN_URL = "https://api.avito.ru/oauth/token"

def get_auth_url(state: str) -> str:
    """
    Генерирует URL для авторизации пользователя в Avito.
    :param state: client_id, который вернётся в callback
    """
    params = {
        "client_id": settings.avito_client_id,
        "redirect_uri": settings.avito_redirect_uri,
        "response_type": "code",
        "scope": "user:read messenger:read messenger:write",
        "state": state,
    }
    return f"{AVITO_AUTH_URL}?{urlencode(params)}"

async def exchange_code_for_token(code: str) -> Optional[Dict[str, Any]]:
    """Обменивает временный код на access_token и refresh_token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            AVITO_TOKEN_URL,
            data={
                "client_id": settings.avito_client_id,
                "client_secret": settings.avito_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.avito_redirect_uri,
            }
        )
    if response.status_code != 200:
        logger.error(f"Failed to exchange code: {response.text}")
        return None
    return response.json()

async def refresh_access_token(refresh_token: str) -> Optional[Dict[str, Any]]:
    """Обновляет access_token по refresh_token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            AVITO_TOKEN_URL,
            data={
                "client_id": settings.avito_client_id,
                "client_secret": settings.avito_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )
    if response.status_code != 200:
        logger.error(f"Failed to refresh token: {response.text}")
        return None
    return response.json()

async def save_avito_account(
    client_id: str,
    avito_user_id: int,
    avito_profile_id: Optional[int],
    token_data: Dict[str, Any]
):
    """Сохраняет информацию о подключенном аккаунте Avito в таблицу avito_accounts."""
    pool = get_db_pool()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO avito_accounts
                (client_id, avito_user_id, avito_profile_id, access_token, refresh_token, token_expires_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (client_id, avito_user_id) DO UPDATE SET
                access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                token_expires_at = EXCLUDED.token_expires_at,
                updated_at = now()
        """,
            client_id,
            avito_user_id,
            avito_profile_id,
            token_data["access_token"],
            token_data["refresh_token"],
            expires_at.isoformat()
        )
        logger.info(f"✅ Avito account for client {client_id} saved/updated")