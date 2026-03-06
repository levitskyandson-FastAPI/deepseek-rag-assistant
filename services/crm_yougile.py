import httpx
from core.logger import logger

YOUGILE_API_URL = "https://yougile.com/api-v2/tasks"

async def send_lead(client_config: dict, lead_data: dict) -> dict:
    token = client_config.get("api_token")
    project_id = client_config.get("project_id")
    column_id = client_config.get("column_id")

    if not token or not project_id or not column_id:
        logger.error("YouGile: не хватает параметров в конфигурации")
        return {"success": False, "error": "missing_params"}

    description = (
        f"Имя: {lead_data.get('name', '')}\n"
        f"Компания: {lead_data.get('company', '')}\n"
        f"Должность: {lead_data.get('position', '')}\n"
        f"Телефон: {lead_data.get('phone', '')}\n"
        f"Бюджет: {lead_data.get('budget', '')}\n"
        f"Сфера: {lead_data.get('industry', '')}\n"
        f"Боль: {lead_data.get('problem', '')}\n"
        f"Текущий процесс: {lead_data.get('current_process', '')}\n"
        f"Объём: {lead_data.get('volume', '')}\n"
        f"Цель: {lead_data.get('goal', '')}\n"
        f"ЛПР/согласование: {lead_data.get('authority_confirmation', '')}\n"
        f"Сроки решения: {lead_data.get('decision_timeline', '')}\n"
        f"Предпочтительная дата созвона: {lead_data.get('preferred_date', '')}"
    )

    payload = {
        "title": f"Лид: {lead_data.get('name', '')} - {lead_data.get('company', '')}",
        "description": description,
        "columnId": column_id,
        "archived": False,
        "_links": {}
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(YOUGILE_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            logger.info(f"✅ Задача в YouGile создана, ID: {result.get('id')}")
            return {"success": True, "ids": {"task_id": result.get("id")}}
    except Exception as e:
        logger.error(f"❌ Ошибка создания задачи в YouGile: {e}")
        return {"success": False, "error": str(e)}