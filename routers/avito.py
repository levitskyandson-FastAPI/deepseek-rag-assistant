from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional
import httpx

from core.logger import logger
from services.db import get_db_pool
from services.avito_auth import get_auth_url, exchange_code_for_token, save_avito_account
from config import settings

router = APIRouter(prefix="/api/v1/avito", tags=["avito"])


@router.get("/connect/{client_id}")
async def connect_page(client_id: str):
    """
    Страница с кнопкой «Подключить Avito».
    Генерирует ссылку на авторизацию Avito с переданным state = client_id.
    """
    auth_url = get_auth_url(state=client_id)
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Подключение Avito</title>
        <style>
            body {{ font-family: Arial, sans-serif; text-align: center; padding-top: 50px; }}
            .button {{
                display: inline-block;
                padding: 15px 30px;
                font-size: 18px;
                color: white;
                background-color: #00AAFF;
                border-radius: 5px;
                text-decoration: none;
                margin-top: 20px;
            }}
        </style>
    </head>
    <body>
        <h1>Подключение аккаунта Avito</h1>
        <p>Нажмите кнопку ниже, чтобы авторизовать ваш аккаунт Avito для работы с AI-ассистентом.</p>
        <a class="button" href="{auth_url}">Подключить Avito</a>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@router.get("/oauth/callback")
async def oauth_callback(code: str, state: Optional[str] = None):
    """
    Обработка редиректа от Avito после авторизации.
    Получает код, обменивает на токены и сохраняет аккаунт в БД.
    """
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    if not state:
        raise HTTPException(status_code=400, detail="Missing state (client_id)")

    client_id = state

    try:
        token_data = await exchange_code_for_token(code)
        if not token_data:
            raise HTTPException(status_code=400, detail="Failed to obtain tokens")

        async with httpx.AsyncClient() as client:
            user_info_resp = await client.get(
                "https://api.avito.ru/core/v1/accounts/self",
                headers={"Authorization": f"Bearer {token_data['access_token']}"}
            )
            user_info_resp.raise_for_status()
            user_data = user_info_resp.json()

        await save_avito_account(
            client_id=client_id,
            avito_user_id=user_data["id"],
            avito_profile_id=user_data.get("profile_id"),
            token_data=token_data
        )

        return HTMLResponse(content="""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"><title>Успех</title></head>
        <body style="font-family: Arial; text-align: center; padding-top: 50px;">
            <h1 style="color: green;">✅ Аккаунт Avito успешно подключен!</h1>
            <p>Теперь вы можете закрыть это окно. Ассистент начнёт отвечать на сообщения в ближайшее время.</p>
        </body>
        </html>
        """)

    except Exception as e:
        logger.error(f"Error in Avito OAuth callback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during Avito connection")
@router.get("/test")
async def test():
    return {"status": "avito router works"}