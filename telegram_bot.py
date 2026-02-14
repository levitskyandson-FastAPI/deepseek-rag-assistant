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

# Простые эвристики для извлечения имени и компании
def extract_name(text):
    # Ищем фразы типа "меня зовут Иван", "зовут Иван", "имя Иван"
    patterns = [
        r'(?:меня зовут|зовут|мое имя|имя)\s+([А-ЯЁ][а-яё]+)',
        r'([А-ЯЁ][а-яё]+)\s+(?:на связи|на линии)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def extract_company(text):
    # Ищем фразы типа "компания Рога и Копыта", "ООО Рога", "ИП Иванов"
    patterns = [
        r'(?:компания|фирма|организация|ооо|ип|зао|ао)\s+([А-ЯЁ][А-ЯЁа-яё\s]+?)(?:\s|\.|,|$|и)',
        r'([А-ЯЁ][А-ЯЁа-яё\s]{2,}?)\s+(?:компания|фирма)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None

def extract_industry(text):
    # Ищем сферу: "сфера продажи", "торговля", "логистика" и т.п.
    keywords = ['торговля', 'продажи', 'логистика', 'медицина', 'образование',
                'строительство', 'производство', 'услуги', 'ритейл', 'e-commerce']
    for word in keywords:
        if word in text.lower():
            return word
    # Можно также искать фразы типа "работаем в сфере..."
    match = re.search(r'(?:сфера|область|отрасль)\s+([а-яё\s]+?)(?:\s|\.|,|$)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None

user_sessions = defaultdict(lambda: {
    "stage": "initial",        # initial, gathering_info, offering, completed
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

    # --- Попытка извлечь имя, компанию, сферу из сообщения ---
    extracted_name = extract_name(user_message)
    if extracted_name and not session["collected"].get("name"):
        session["collected"]["name"] = extracted_name

    extracted_company = extract_company(user_message)
    if extracted_company and not session["collected"].get("company"):
        session["collected"]["company"] = extracted_company

    extracted_industry = extract_industry(user_message)
    if extracted_industry and not session["collected"].get("industry"):
        session["collected"]["industry"] = extracted_industry
    # --------------------------------------------------------

    # Проверка на номер телефона (этот блок остаётся выше остальных)
    phone_match = PHONE_REGEX.search(user_message)
    if phone_match and session["stage"] != "completed":
        phone = phone_match.group()
        name = session["collected"].get("name")
        company = session["collected"].get("company")
        industry = session["collected"].get("industry")
        pain = session["collected"].get("pain")

        # Парсим дату и время
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
        if name:
            session["collected"]["name"] = name
        if company:
            session["collected"]["company"] = company
        if industry:
            session["collected"]["industry"] = industry
        if pain:
            session["collected"]["pain"] = pain
        if preferred_date:
            session["collected"]["preferred_date"] = preferred_date

        # Сохраняем лида в Supabase
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
            print(f"Ошибка сохранения лида: {e}")

        session["stage"] = "completed"
        reply = "Спасибо! Я передал ваш номер менеджеру. "
        if preferred_date:
            reply += f"Вы выбрали {preferred_date}. "
        if name:
            reply += f"Мы запомнили ваше имя, {name}. "
        reply += "Он свяжется с вами в ближайшее время для согласования удобного времени консультации."
        await update.message.reply_text(reply)
        return

    # Определяем, какие данные уже собраны, а какие нет
    collected = session["collected"]
    missing = []
    if not collected.get("name"):
        missing.append("имя")
    if not collected.get("company"):
        missing.append("название компании")
    if not collected.get("industry"):
        missing.append("сфера деятельности")

    # Формируем system_extra в зависимости от стадии и недостающих данных
    system_extra = ""

    if session["stage"] == "initial":
        # Если есть недостающие данные, переходим в стадию сбора информации
        if missing:
            session["stage"] = "gathering_info"
            # Будем собирать по одному, начнём с первого недостающего
            next_field = missing[0]
            field_prompts = {
                "имя": "Спроси у клиента его имя, если оно ещё не известно.",
                "название компании": "Спроси название компании клиента.",
                "сфера деятельности": "Спроси, в какой сфере работает компания клиента."
            }
            system_extra = field_prompts.get(next_field, "Задай уточняющий вопрос.")
        else:
            # Все данные уже есть, можно выяснять потребность
            system_extra = (
                "Ты — продающий консультант. Клиент предоставил все данные. "
                "Теперь выясни его потребность (боль). Задавай открытые вопросы: "
                "'Расскажите подробнее о вашей задаче?', 'С какими трудностями вы сталкиваетесь?'."
            )
    elif session["stage"] == "gathering_info":
        if missing:
            # Спрашиваем по очереди
            next_field = missing[0]
            field_prompts = {
                "имя": "Если имя клиента всё ещё не известно, спроси его. Если уже известно, переходи к следующему пункту.",
                "название компании": "Если название компании всё ещё не известно, спроси его. Если уже известно, переходи к следующему пункту.",
                "сфера деятельности": "Если сфера деятельности всё ещё не известна, спроси её. Если уже известна, переходи к выяснению боли."
            }
            system_extra = field_prompts.get(next_field, "Задай уточняющий вопрос.")
            # Если после ответа все данные собраны, перейдём к выяснению боли в следующем шаге
            if not missing:  # если после обновления всё собрано
                session["stage"] = "collecting_pain"
                system_extra = "Все данные собраны. Теперь выясни потребность клиента (боль)."
        else:
            # Все данные собраны, переходим к сбору боли
            session["stage"] = "collecting_pain"
            system_extra = "Все данные собраны. Теперь выясни потребность клиента (боль). Задай открытые вопросы."

    elif session["stage"] == "collecting_pain":
        # Если боль ещё не собрана (нет в collected), спрашиваем
        if not collected.get("pain"):
            system_extra = "Выясни потребность клиента (боль). Задай открытые вопросы."
        else:
            # Боль есть, переходим к предложению консультации
            session["stage"] = "offer_consultation"
            system_extra = "Ты уже выяснил проблему клиента. Теперь нужно предложить бесплатную консультацию. Попроси его выбрать удобное время и оставить номер телефона."

    elif session["stage"] == "offer_consultation":
        system_extra = (
            "Ты уже выяснил проблему клиента. Теперь нужно предложить бесплатную консультацию. "
            "Попроси его выбрать удобное время и оставить номер телефона."
        )

    elif session["stage"] == "completed":
        system_extra = "Ответь на вопрос клиента максимально полезно, учитывая, что консультация уже назначена."

    # Формируем context_info
    context_info = {
        "stage": session["stage"],
        "greeted": session.get("greeted", False),
        "collected": collected
    }

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

    # После ответа обновляем greeted
    if not session["greeted"]:
        session["greeted"] = True

    # Если модель всё же предложила номер, а мы ещё не в offer_consultation, переводим
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