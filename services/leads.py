from services.supabase import supabase
from core.logger import logger

async def save_lead(telegram_user_id: int, name: str = None, phone: str = None, 
                    company: str = None, industry: str = None, 
                    preferred_date: str = None, pain: str = None, 
                    extra_data: dict = None):
    try:
        logger.info(f"📥 save_lead вызван: user_id={telegram_user_id}, phone={phone}, name={name}, company={company}")
        
        if not phone:
            logger.warning("❌ Попытка сохранить лид без телефона")
            return None

        data = {
            "telegram_user_id": telegram_user_id,
            "phone": phone,
            "pain_description": pain,
            "collected_data": extra_data or {}
        }
        if name:
            data["name"] = name
        if company:
            data["company"] = company
        if industry:
            data["industry"] = industry
        if preferred_date:
            data["preferred_date"] = preferred_date

        logger.info(f"📦 Данные для вставки: {data}")
        result = supabase.table("leads").insert(data).execute()
        logger.info(f"✅ Лид сохранён, результат: {result.data}")
        return result.data
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения лида: {e}", exc_info=True)
        raise