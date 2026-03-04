import asyncio
import httpx
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from core.logger import logger
from services.db import get_db_pool
from services.avito_auth import refresh_access_token
from services.deepseek import ask_with_rag  # ваша основная функция

async def refresh_expired_tokens():
    """Периодически обновляет истекшие токены (проверяет каждые 30 мин)."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, client_id, refresh_token
            FROM avito_accounts
            WHERE token_expires_at < now() + interval '1 hour'
        """)
        for row in rows:
            token_data = await refresh_access_token(row['refresh_token'])
            if token_data:
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])
                await conn.execute("""
                    UPDATE avito_accounts
                    SET access_token = $1, token_expires_at = $2, updated_at = now()
                    WHERE id = $3
                """, token_data["access_token"], expires_at.isoformat(), row['id'])
                logger.info(f"🔄 Refreshed token for account {row['id']}")

async def fetch_new_messages():
    """Получает новые сообщения из всех чатов всех аккаунтов."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        accounts = await conn.fetch("""
            SELECT id, client_id, access_token, avito_user_id
            FROM avito_accounts
            WHERE token_expires_at > now()
        """)
    for account in accounts:
        await process_account_messages(account)

async def process_account_messages(account: Dict[str, Any]):
    """Обрабатывает все чаты и сообщения для одного аккаунта Avito."""
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    pool = get_db_pool()

    async with httpx.AsyncClient() as client:
        # Получаем список чатов
        chats_resp = await client.get(
            "https://api.avito.ru/messenger/v2/accounts/self/chats",
            headers=headers,
            params={"limit": 50}
        )
        if chats_resp.status_code != 200:
            logger.error(f"❌ Failed to get chats for account {account['id']}: {chats_resp.text}")
            return
        chats = chats_resp.json().get("chats", [])
        for chat in chats:
            await process_chat_messages(account, chat)

async def process_chat_messages(account: Dict[str, Any], chat: Dict[str, Any]):
    """Сохраняет информацию о чате и обрабатывает новые сообщения."""
    pool = get_db_pool()
    # Сохраняем или обновляем чат
    async with pool.acquire() as conn:
        chat_record = await conn.fetchrow("""
            INSERT INTO avito_chats (avito_account_id, chat_id, chat_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (avito_account_id, chat_id) DO UPDATE SET
                updated_at = now()
            RETURNING id
        """, account['id'], chat['id'], chat.get('type'))
        chat_db_id = chat_record['id']

    headers = {"Authorization": f"Bearer {account['access_token']}"}
    async with httpx.AsyncClient() as client:
        # Получаем последние сообщения чата (до 50)
        msgs_resp = await client.get(
            f"https://api.avito.ru/messenger/v2/accounts/self/chats/{chat['id']}/messages",
            headers=headers,
            params={"limit": 50}
        )
        if msgs_resp.status_code != 200:
            logger.error(f"❌ Failed to get messages for chat {chat['id']}: {msgs_resp.text}")
            return
        messages = msgs_resp.json().get("messages", [])
        for msg in messages:
            await process_single_message(account, chat_db_id, chat['id'], msg)

async def process_single_message(
    account: Dict[str, Any],
    chat_db_id: str,
    chat_id: str,
    msg: Dict[str, Any]
):
    """Сохраняет сообщение и, если оно от пользователя, генерирует ответ через ИИ."""
    pool = get_db_pool()
    is_from_us = msg.get("author_id") == account['avito_user_id']

    async with pool.acquire() as conn:
        existing = await conn.fetchval("""
            SELECT id FROM avito_messages
            WHERE avito_chat_id = $1 AND message_id = $2
        """, chat_db_id, msg['id'])
        if existing:
            return  # уже было

        await conn.execute("""
            INSERT INTO avito_messages
                (avito_chat_id, message_id, content, is_from_us, sent_at)
            VALUES ($1, $2, $3, $4, $5)
        """, chat_db_id, msg['id'], msg.get('content', {}).get('text', ''),
            is_from_us, msg.get('created_at'))

    if not is_from_us:
        user_text = msg.get('content', {}).get('text', '')
        if not user_text:
            return

        # Вызываем ИИ
        reply, sources = await ask_with_rag(
            user_message=user_text,
            user_id=account['client_id'],
            use_rag=True,
            context_info=json.dumps({"source": "avito", "chat_id": chat_id})
        )
        await send_avito_message(account, chat_id, reply)

async def send_avito_message(account: Dict[str, Any], chat_id: str, text: str):
    """Отправляет сообщение в чат Avito."""
    headers = {"Authorization": f"Bearer {account['access_token']}"}
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.avito.ru/messenger/v2/accounts/self/chats/{chat_id}/messages",
            headers=headers,
            json={"message": {"text": text}}
        )
        if response.status_code != 200:
            logger.error(f"❌ Failed to send message to chat {chat_id}: {response.text}")
        else:
            logger.info(f"✅ Message sent to Avito chat {chat_id}")

async def avito_worker_loop():
    """Основной цикл воркера, запускается в фоне."""
    while True:
        try:
            await refresh_expired_tokens()
            await fetch_new_messages()
        except Exception as e:
            logger.exception(f"🔥 Avito worker error: {e}")
        await asyncio.sleep(30)  # пауза 30 секунд