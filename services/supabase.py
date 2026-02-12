from supabase import create_client, Client
from config import settings
from core.logger import logger

try:
    supabase: Client = create_client(
        settings.supabase_url,
        settings.supabase_key
    )
    logger.info("✅ Подключение к Supabase установлено")
except Exception as e:
    logger.error(f"❌ Ошибка подключения к Supabase: {e}")
    raise

def get_supabase() -> Client:
    return supabase