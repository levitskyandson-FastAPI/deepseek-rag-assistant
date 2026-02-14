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

# ---------- Улучшенное извлечение имени ----------
def extract_name(text):
    print(f"[extract_name] Анализируем: '{text}'")
    # Нормализация пробелов
    text = re.sub(r'\s+', ' ', text).strip()
    patterns = [
        # 1. "меня зовут Иван", "зовут Иван", "мое имя Иван", "имя Иван"
        r'(?:меня\s+зовут|зовут|мое\s+имя|имя)\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)',
        # 2. "Иван на связи", "Иван на линии"
        r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s+(?:на\s+связи|на\s+линии)',
        # 3. просто имя в начале сообщения (например, "Денис, ..." или "Денис")
        r'^([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)[,\s]',
        # 4. если сообщение состоит только из имени (возможно, с отчеством)
        r'^([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)$',
        # 5. имя перед тире или после тире (например, "Денис Левицкий — CEO")
        r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*[—–-]',
        r'[—–-]\s*([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)',
        # 6. последний шанс — любое слово с большой буквы (осторожно)
        r'\b([А-ЯЁ][а-яё]+)\b'
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            print(f"[extract_name] НАЙДЕНО: '{name}' по шаблону {pattern}")
            return name
    print("[extract_name] Имя не найдено")
    return None

# ---------- Извлечение компании ----------
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
    print("[extract_company] Не найдено")
    return None

# ---------- Извлечение сферы ----------
def extract_industry(text):
    keywords = ['торговля', 'продажи', 'логистика', 'медицина', 'образование',
                'строительство', 'производство', 'услуги', 'ритейл', 'e-commerce']
    for word in keywords:
        if word in text.lower():
            print(f"[extract_industry] НАЙДЕНО ПО КЛЮЧЕВОМУ СЛОВУ: '{word}'")
            return word
    match = re.search(r'(?:сфера|область|отрасль)\s+([а-яё\s]+?)(?:\s|\.|,|$)', text, re.IGNORECASE)
    if match:
        industry = match.group(1).strip()
        print(f"[extract_industry] НАЙДЕНО ПО ФРАЗЕ: '{industry}'")
        return industry
    print("[extract_industry] Не найдено")
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

    # --- Извлечение данных из сообщения ---
    extracted_name = extract_name(user_message)
    if extracted_name and not session["collected"].get("name"):
        session["collected"]["name"] = extracted_name
        print(f"✅ Имя сохранено в сессии: {extracted_name}")

    extracted_company = extract_company(user_message)
    if extracted_company and not session["collected"].get("company"):
        session["collected"]["company"] = extracted_company
        print(f"✅ Компания сохранена: {extracted_company}")

    extracted_industry = extract_industry(user_message)
    if extracted_industry and not session["collected"].get("industry"):
        session["collected"]["industry"] = extracted_industry
        print(f"✅ Сфера сохранена: {extracted_industry}")
    # ----------------------------------------

    # Проверка на номер телефона (этот блок должен быть до остальной обработки)
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

    # Определяем, какие данные уже собраны
    collected = session["collected"]
    missing = []
    if not collected.get("name"):
        missing.append("имя")
    if not collected.get("company"):
        missing.append("название компании")
    if not collected.get("industry"):
        missing.append("сфера деятельности")

    # Формируем строку с уже известными данными для system_extra
    known_info_parts = []
    if collected.get("name"):
        known_info_parts.append(f"имя: {collected['name']}")
    if collected.get("company"):
        known_info_parts.append(f"компания: {collected['company']}")
    if collected.get("industry"):
        known_info_parts.append(f"сфера: {collected['industry']}")
    if collected.get("preferred_date"):
        known_info_parts.append(f"консультация назначена на {collected['preferred_date']}")
    known_info_str = "Известно: " + ", ".join(known_info_parts) + ". " if known_info_parts else ""

    # Определяем стадию и формируем system_extra
    system_extra = ""

    if session["stage"] == "initial":
        if missing:
            session["stage"] = "gathering_info"
            next_field = missing[0]
            if next_field == "имя":
                system_extra = known_info_str + "Спроси у клиента его имя. Не давай никакой другой информации, не рассказывай о компании."
            elif next_field == "название компании":
                system_extra = known_info_str + "Спроси название компании клиента. Не давай справок."
            elif next_field == "сфера деятельности":
                system_extra = known_info_str + "Спроси, в какой сфере работает компания клиента. Не давай справок."
        else:
            session["stage"] = "collecting_pain"
            system_extra = known_info_str + "Все данные собраны. Теперь выясни потребность клиента (боль). Задавай открытые вопросы, не предлагай услуги."

    elif session["stage"] == "gathering_info":
        if missing:
            next_field = missing[0]
            if next_field == "имя":
                system_extra = known_info_str + "Имя клиента всё ещё неизвестно. Спроси его. Не давай другой информации."
            elif next_field == "название компании":
                system_extra = known_info_str + "Название компании ещё неизвестно. Спроси его. Не рассказывай о себе."
            elif next_field == "сфера деятельности":
                system_extra = known_info_str + "Сфера деятельности ещё неизвестна. Спроси её. Не давай справок."
        else:
            session["stage"] = "collecting_pain"
            system_extra = known_info_str + "Все данные собраны. Выясни потребность клиента."

    elif session["stage"] == "collecting_pain":
        if not collected.get("pain"):
            system_extra = known_info_str + "Выясни потребность клиента (боль). Задавай открытые вопросы. Не предлагай консультацию, пока не поймёшь проблему."
        else:
            session["stage"] = "offer_consultation"
            system_extra = known_info_str + "Ты уже выяснил проблему клиента. Предложи бесплатную консультацию, попроси выбрать удобное время и оставить номер телефона."

    elif session["stage"] == "offer_consultation":
        system_extra = known_info_str + "Предложи бесплатную консультацию. Попроси выбрать время и оставить номер телефона. Не задавай больше вопросов."

    elif session["stage"] == "completed":
        system_extra = known_info_str + "Ответь на вопрос клиента максимально полезно, используя известные данные. Не предлагай больше консультаций."

    # Формируем context_info
    context_info = {
        "stage": session["stage"],
        "greeted": session.get("greeted", False),
        "collected": collected
    }

    # Логируем то, что отправляем в API
    print(f"➡️ Отправка в API: stage={session['stage']}, missing={missing}, known={known_info_parts}")
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

    # Если модель предложила номер, а мы ещё не в offer_consultation, переводим
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