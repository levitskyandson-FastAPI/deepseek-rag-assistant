from services.supabase import supabase
from core.logger import logger

async def save_lead(telegram_user_id: int, name: str = None, phone: str = None, preferred_date: str = None, pain: str = None, extra_data: dict = None):
    """
    Сохраняет данные лида в таблицу leads.
    """
    try:
        if not phone:
            logger.warning("Попытка сохранить лид без телефона")
            return None

        data = {
            "telegram_user_id": telegram_user_id,
            "phone": phone,
            "pain_description": pain,
            "collected_data": extra_data or {}
        }
        if name:
            data["name"] = name
        if preferred_date:
            data["preferred_date"] = preferred_date

        result = supabase.table("leads").insert(data).execute()
        logger.info(f"✅ Лид сохранён для пользователя {telegram_user_id}, phone: {phone}")
        return result.data
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения лида: {e}", exc_info=True)
        raise