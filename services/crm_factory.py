import importlib
from core.logger import logger

CRM_MODULES = {
    "amo": "crm_amo",
    "yougile": "crm_yougile",
}

async def send_lead_to_all(client_data: dict, lead_data: dict) -> dict:
    crm_config = client_data.get("crm_config", {})
    if not isinstance(crm_config, dict):
        logger.error(f"Некорректный crm_config для клиента {client_data.get('id')}")
        return {}

    results = {}
    for crm_key, config in crm_config.items():
        if not config.get("enabled", False):
            continue

        module_name = CRM_MODULES.get(crm_key)
        if not module_name:
            logger.warning(f"Неизвестная CRM: {crm_key}")
            continue

        try:
            module = importlib.import_module(f"services.{module_name}")
            if hasattr(module, "send_lead"):
                result = await module.send_lead(config, lead_data)
                results[crm_key] = result
            else:
                logger.error(f"Модуль {module_name} не содержит функцию send_lead")
        except Exception as e:
            logger.exception(f"Ошибка при вызове CRM {crm_key}: {e}")
            results[crm_key] = {"success": False, "error": str(e)}

    return results