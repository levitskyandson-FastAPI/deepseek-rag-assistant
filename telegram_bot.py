import os
import re
import json
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict

import nest_asyncio
nest_asyncio.apply()

from services.leads import save_lead

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_URL = "https://deepseek-rag-assistant-1-ldph.onrender.com/chat/"
USER_ID = "levitsky_agency"

PHONE_REGEX = re.compile(r'\+?[0-9]{10,15}')

# ---------- Извлечение данных ----------
def extract_name(text):
    print(f"[extract_name] Анализируем: '{text}'")
    text = re.sub(r'\s+', ' ', text).strip()
    patterns = [
        r'(?:меня зовут|зовут|мое имя|имя)\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)',
        r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s+(?:на связи|на линии)',
        r'^([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)[,\s]',
        r'^([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)$',
        r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*[—–-]',
        r'[—–-]\s*([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)',
        r'\b([А-ЯЁ][а-яё]+)\b'
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            print(f"[extract_name] НАЙДЕНО: '{name}'")
            return name
    return None

def extract_company(text):
    patterns = [
        r'(?:компания|фирма|организация|ооо|ип|зао|ао)\s+([А-ЯЁ][А-ЯЁа-яё\s]+?)(?:\s|\.|,|$|и)',
        r'([А-ЯЁ][А-ЯЁа-яё\s]{2,}?)\s+(?:компания|фирма)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            company = match.group(1).strip()
            print(f"[extract_company] НАЙДЕНО: '{company}'")
            return company
    return None

def extract_industry(text):
    keywords = ['торговля', 'продажи', 'логистика', 'медицина', 'образование',
                'строительство', 'производство', 'услуги', 'ритейл', 'e-commerce']
    for word in keywords:
        if word in text.lower():
            print(f"[extract_industry] НАЙДЕНО: '{word}'")
            return word
    match = re.search(r'(?:сфера|область|отрасль)\s+([а-яё\s]+?)(?:\s|\.|,|$)', text, re.IGNORECASE)
    if match:
        industry = match.group(1).strip()
        print(f"[extract_industry] НАЙДЕНО: '{industry}'")
        return industry
    return None
# ------------------------------------------------

user_sessions = defaultdict(lambda: {
    "stage": "initial",        # initial, gathering_info, collecting_pain, offer_consultation, completed
    "greeted": False,
    "collected": {}
})

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = {
        "stage": "initial",
        "greeted": True,
        "collected": {}
    }
    await update.message.reply_text(
        "👋 Добро пожаловать в Levitsky & Son AI Solutions!\n\n"
        "Я — ваш ИИ-консультант. Расскажите, какая у вас задача, и я помогу подобрать решение."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    session = user_sessions[user_id]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # --- Извлечение данных ---
    extracted_name = extract_name(user_message)
    if extracted_name and not session["collected"].get("name"):
        session["collected"]["name"] = extracted_name
        print(f"✅ Имя сохранено: {extracted_name}")

    extracted_company = extract_company(user_message)
    if extracted_company and not session["collected"].get("company"):
        session["collected"]["company"] = extracted_company
        print(f"✅ Компания сохранена: {extracted_company}")

    extracted_industry = extract_industry(user_message)
    if extracted_industry and not session["collected"].get("industry"):
        session["collected"]["industry"] = extracted_industry
        print(f"✅ Сфера сохранена: {extracted_industry}")
    # -------------------------

    # Проверка номера телефона (приоритетно)
    phone_match = PHONE_REGEX.search(user_message)
    if phone_match and session["stage"] != "completed":
        phone = phone_match.group()
        name = session["collected"].get("name")
        company = session["collected"].get("company")
        industry = session["collected"].get("industry")
        pain = session["collected"].get("pain")

        # Парсинг даты и времени
        preferred_date = None
        msg_lower = user_message.lower()
        if "сегодня" in msg_lower:
            preferred_date = "сегодня"
        elif "завтра" in msg_lower:
            preferred_date = "завтра"
        elif "послезавтра" in msg_lower:
            preferred_date = "послезавтра"

        time_match = re.search(r'(\d{1,2})[:–-.](\d{2})', user_message)
        if not time_match:
            time_match = re.search(r'в\s+(\d{1,2})(?:\s|$)', user_message)
        if time_match:
            hour = time_match.group(1)
            minute = time_match.group(2) if len(time_match.groups()) > 1 else "00"
            time_str = f"{hour}:{minute}"
            if preferred_date:
                preferred_date = f"{preferred_date} в {time_str}"
            else:
                preferred_date = time_str

        # Сохраняем в сессию
        session["collected"]["phone"] = phone
        if name: session["collected"]["name"] = name
        if company: session["collected"]["company"] = company
        if industry: session["collected"]["industry"] = industry
        if pain: session["collected"]["pain"] = pain
        if preferred_date: session["collected"]["preferred_date"] = preferred_date

        # Сохраняем в Supabase
        try:
            await save_lead(
                telegram_user_id=user_id,
                name=name,
                phone=phone,
                company=company,
                industry=industry,
                pain=pain,
                preferred_date=preferred_date,
                extra_data={"source": "telegram_bot", "stage": session["stage"]}
            )
        except Exception as e:
            print(f"❌ Ошибка сохранения лида: {e}")

        session["stage"] = "completed"
        reply = "Спасибо! Я передал ваш номер менеджеру. "
        if preferred_date:
            reply += f"Вы выбрали {preferred_date}. "
        if name:
            reply += f"Мы запомнили ваше имя, {name}. "
        reply += "Он свяжется с вами в ближайшее время для согласования удобного времени консультации."
        await update.message.reply_text(reply)
        return

    # Определяем недостающие поля
    collected = session["collected"]
    missing = []
    if not collected.get("name"):
        missing.append("имя")
    if not collected.get("company"):
        missing.append("название компании")
    if not collected.get("industry"):
        missing.append("сфера деятельности")

    # Формируем строку известных данных
    known_info_parts = []
    if collected.get("name"): known_info_parts.append(f"имя: {collected['name']}")
    if collected.get("company"): known_info_parts.append(f"компания: {collected['company']}")
    if collected.get("industry"): known_info_parts.append(f"сфера: {collected['industry']}")
    if collected.get("preferred_date"): known_info_parts.append(f"консультация назначена на {collected['preferred_date']}")
    known_info_str = "Известно: " + ", ".join(known_info_parts) + ". " if known_info_parts else ""

    # Управление стадиями с максимально строгими инструкциями
    system_extra = ""

    if session["stage"] == "initial":
        if missing:
            session["stage"] = "gathering_info"
            next_field = missing[0]
            if next_field == "имя":
                system_extra = "Твоя задача: задать только один вопрос — спросить имя клиента. Не пиши ничего лишнего, не представляйся, не рассказывай о компании. Твой ответ должен состоять только из вопроса об имени."
            elif next_field == "название компании":
                system_extra = "Твоя задача: задать только один вопрос — спросить название компании клиента. Не пиши ничего лишнего."
            elif next_field == "сфера деятельности":
                system_extra = "Твоя задача: задать только один вопрос — спросить сферу деятельности компании. Не пиши ничего лишнего."
        else:
            session["stage"] = "collecting_pain"
            system_extra = known_info_str + "Твоя задача: задать открытый вопрос о проблеме клиента (боли). Например: 'Расскажите подробнее, с какими трудностями вы сталкиваетесь в обработке заявок?' Не добавляй никакой другой информации."

    elif session["stage"] == "gathering_info":
        if missing:
            next_field = missing[0]
            if next_field == "имя":
                system_extra = "Твоя задача: спросить имя клиента. Не пиши ничего, кроме вопроса."
            elif next_field == "название компании":
                system_extra = "Твоя задача: спросить название компании. Не пиши ничего, кроме вопроса."
            elif next_field == "сфера деятельности":
                system_extra = "Твоя задача: спросить сферу деятельности. Не пиши ничего, кроме вопроса."
        else:
            session["stage"] = "collecting_pain"
            system_extra = known_info_str + "Твоя задача: спросить о проблеме клиента. Не добавляй лишнего."

    elif session["stage"] == "collecting_pain":
        if not collected.get("pain"):
            system_extra = known_info_str + "Твоя задача: спросить о проблеме клиента (боль). Не предлагай консультацию, не рассказывай о компании. Просто задай вопрос."
        else:
            session["stage"] = "offer_consultation"
            system_extra = known_info_str + "Твоя задача: предложить бесплатную консультацию и попросить номер телефона и удобное время. Например: 'Для более точного расчёта предлагаю бесплатную консультацию с нашим специалистом. Выберите, пожалуйста, удобное время для звонка и оставьте ваш номер телефона.' Не задавай других вопросов."

    elif session["stage"] == "offer_consultation":
        system_extra = known_info_str + "Твоя задача: предложить консультацию и попросить номер телефона и время. Не пиши ничего другого."

    elif session["stage"] == "completed":
        system_extra = known_info_str + "Твоя задача: отвечать на вопросы клиента, используя известные данные. Если вопрос не по теме, скажи, что можешь помочь только по услугам компании. Не предлагай больше консультаций."

    # Формируем context_info
    context_info = {
        "stage": session["stage"],
        "greeted": session.get("greeted", False),
        "collected": collected
    }

    print(f"➡️ stage={session['stage']}, missing={missing}, known={known_info_parts}")
    print(f"➡️ system_extra: {system_extra}")

    try:
        payload = {
            "user_id": USER_ID,
            "message": user_message,
            "use_rag": True,
            "system_extra": system_extra,
            "context_info": json.dumps(context_info, ensure_ascii=False)
        }
        headers = {"Content-Type": "application/json"}
        response = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        reply = data.get("reply", "⚠️ Не удалось получить ответ.")
    except Exception as e:
        reply = f"❌ Ошибка: {e}"

    if not session["greeted"]:
        session["greeted"] = True

    # Если модель сама предложила номер, переводим стадию
    if "оставьте ваш номер" in reply and session["stage"] not in ("offer_consultation", "completed"):
        session["stage"] = "offer_consultation"

    await update.message.reply_text(reply)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Telegram Bot запущен и готов к работе!")
    app.run_polling()

if __name__ == "__main__":
    main()