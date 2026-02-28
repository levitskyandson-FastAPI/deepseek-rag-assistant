import json
from services.db import get_db_pool
from core.logger import logger

async def save_lead(
    telegram_user_id: int,
    phone: str,
    client_id: str,
    name: str = None,
    company: str = None,
    industry: str = None,
    preferred_date: str = None,
    pain: str = None,
    goal: str = None,
    extra_data: dict = None
):
    """
    Сохраняет лид в таблицу leads с привязкой к клиенту (client_id).
    Возвращает список с одним словарем, содержащим id новой записи.
    """
    try:
        logger.info(f"📥 save_lead: user={telegram_user_id}, phone={phone}, client={client_id}")

        if not phone:
            logger.warning("❌ Попытка сохранить лид без телефона")
            return None
        if not client_id:
            logger.error("❌ client_id обязателен для сохранения лида")
            return None

        collected = extra_data or {}

        pool = get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO leads (
                    telegram_user_id, phone, name, company, industry,
                    pain_description, goal, preferred_date, collected_data, client_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
            """,
                telegram_user_id,
                phone,
                name,
                company,
                industry,
                pain,
                goal,
                preferred_date,
                json.dumps(collected, ensure_ascii=False),
                client_id
            )

            lead_id = row["id"]
            logger.info(f"✅ Лид сохранён, id={lead_id}")
            return [{"id": lead_id}]

    except Exception as e:
        logger.error(f"❌ Ошибка сохранения лида: {e}", exc_info=True)
        return None