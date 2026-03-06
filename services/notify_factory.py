import importlib
import json
from core.logger import logger

NOTIFIERS = {
    "telegram": "notify_telegram",
    # "email": "notify_email",   # для будущих каналов
    # "slack": "notify_slack",
}

async def send_notifications(bot, client_data: dict, lead_data: dict, event_type: str = "new") -> dict:
    notifications_config = client_data.get("notifications", {})
    if isinstance(notifications_config, str):
        try:
            notifications_config = json.loads(notifications_config)
        except json.JSONDecodeError:
            logger.error(f"Некорректный notifications (строка): {notifications_config[:200]}")
            return {}

    if not isinstance(notifications_config, dict):
        logger.error(f"Некорректный notifications для клиента {client_data.get('id')}: {type(notifications_config)}")
        return {}

    results = {}
    for channel, config in notifications_config.items():
        if not config.get("enabled", False):
            continue

        module_name = NOTIFIERS.get(channel)
        if not module_name:
            logger.warning(f"Неизвестный канал уведомлений: {channel}")
            continue

        try:
            module = importlib.import_module(f"services.{module_name}")
            if hasattr(module, "send"):
                result = await module.send(bot, config, lead_data, event_type)
                results[channel] = result
            else:
                logger.error(f"Модуль {module_name} не содержит функцию send")
        except Exception as e:
            logger.exception(f"Ошибка при отправке уведомления через {channel}: {e}")
            results[channel] = {"success": False, "error": str(e)}

    return results