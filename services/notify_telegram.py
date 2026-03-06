from core.logger import logger
from services.lead_utils import build_lead_summary

async def send(bot, client_config: dict, lead_data: dict, event_type: str) -> dict:
    chat_id = client_config.get("chat_id")
    if not chat_id:
        logger.error("Telegram: отсутствует chat_id в конфигурации")
        return {"success": False, "error": "no_chat_id"}

    header = "🔥 Новый лид" if event_type == "new" else "✏️ Изменения в лиде"
    msg = header + "\n\n" + build_lead_summary(lead_data)

    try:
        await bot.send_message(chat_id=chat_id, text=msg)
        logger.info(f"✅ Уведомление отправлено в Telegram (chat_id={chat_id})")
        return {"success": True}
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в Telegram: {e}")
        return {"success": False, "error": str(e)}