from services.amocrm import AmoCRM
from core.logger import logger

async def send_lead(client_config: dict, lead_data: dict) -> dict:
    account_key = client_config.get("account_key")
    if not account_key:
        logger.error("amoCRM: отсутствует account_key в конфигурации")
        return {"success": False, "error": "no_account_key"}

    try:
        crm = AmoCRM(account_key)
        amo_data = {
            "name": lead_data.get("name"),
            "phone": lead_data.get("phone"),
            "problem": lead_data.get("problem"),
            "goal": lead_data.get("goal"),
            "volume": lead_data.get("volume"),
            "meeting_time": lead_data.get("preferred_date"),
            "sphere": lead_data.get("industry"),
            "budget": lead_data.get("budget"),
            "position": lead_data.get("position"),
            "company": lead_data.get("company"),
            "authority": lead_data.get("authority_confirmation"),
            "timeline": lead_data.get("decision_timeline"),
        }
        result = crm.create_lead(amo_data)
        return {"success": True, "ids": result}
    except Exception as e:
        logger.exception(f"amoCRM error: {e}")
        return {"success": False, "error": str(e)}