import asyncpg
import json
from datetime import datetime
from core.logger import logger
from config import settings

# Строка подключения из настроек (добавьте их в config.py)
DB_DSN = f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}?ssl=require"

_pool = None

async def init_db_pool():
    global _pool
    _pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=10)
    logger.info("✅ Пул соединений с PostgreSQL создан")

async def close_db_pool():
    if _pool:
        await _pool.close()
        logger.info("🔌 Пул соединений закрыт")

def get_db_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Пул БД не инициализирован")
    return _pool

# ---------- Функции для clients ----------
async def get_client(client_id: str) -> dict | None:
    async with get_db_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM clients WHERE id = $1", client_id)
        return dict(row) if row else None

async def get_all_active_clients() -> list[dict]:
    async with get_db_pool().acquire() as conn:
        rows = await conn.fetch("SELECT * FROM clients WHERE is_active = true")
        return [dict(r) for r in rows]

# ---------- Функции для sessions ----------
async def get_session(user_id: int, client_id: str) -> dict | None:
    async with get_db_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM sessions WHERE user_id = $1 AND client_id = $2",
            user_id, client_id
        )
        if row:
            data = dict(row)
            data['conversation'] = json.loads(data['conversation']) if data.get('conversation') else []
            data['collected'] = json.loads(data['collected']) if data.get('collected') else {}
            return data
        return None

async def save_session(user_id: int, client_id: str, session: dict):
    async with get_db_pool().acquire() as conn:
        await conn.execute("""
            INSERT INTO sessions (user_id, client_id, conversation, collected, lead_saved, contact_id, lead_id, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (user_id, client_id) DO UPDATE SET
                conversation = EXCLUDED.conversation,
                collected = EXCLUDED.collected,
                lead_saved = EXCLUDED.lead_saved,
                contact_id = EXCLUDED.contact_id,
                lead_id = EXCLUDED.lead_id,
                updated_at = EXCLUDED.updated_at
        """,
            user_id,
            client_id,
            json.dumps(session['conversation'], ensure_ascii=False),
            json.dumps(session['collected'], ensure_ascii=False),
            session['lead_saved'],
            session.get('contact_id'),
            session.get('lead_id'),
            datetime.now().isoformat()
        )

# ---------- Функции для leads ----------
async def save_lead(telegram_user_id: int, phone: str, name: str = None, company: str = None,
                    industry: str = None, pain: str = None, goal: str = None,
                    preferred_date: str = None, extra_data: dict = None):
    async with get_db_pool().acquire() as conn:
        await conn.execute("""
            INSERT INTO leads (telegram_user_id, phone, name, company, industry, pain_description, goal, preferred_date, collected_data)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
            telegram_user_id,
            phone,
            name,
            company,
            industry,
            pain,
            goal,
            preferred_date,
            json.dumps(extra_data, ensure_ascii=False) if extra_data else None
        )