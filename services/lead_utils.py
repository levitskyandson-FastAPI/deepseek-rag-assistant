# services/lead_utils.py
def build_lead_summary(collected: dict) -> str:
    return f"""
Имя: {collected.get('name')}
Компания: {collected.get('company')}
Сфера: {collected.get('industry')}
Боль: {collected.get('problem')}
Как сейчас: {collected.get('current_process')}
Объём: {collected.get('volume')}
Цель: {collected.get('goal')}
Бюджет: {collected.get('budget')}
Должность: {collected.get('position')}
ЛПР/согласование: {collected.get('authority_confirmation')}
Сроки решения: {collected.get('decision_timeline')}
Телефон: {collected.get('phone')}
Созвон: {collected.get('preferred_date')}
"""