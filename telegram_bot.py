import os
import re
import json
import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict

from services.leads import save_lead
from core.logger import logger

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не задан в переменных окружения")

API_URL = os.getenv("API_URL", "https://deepseek-assistant-api.onrender.com/chat/")
USER_ID = os.getenv("USER_ID", "levitsky_agency")

PHONE_REGEX = re.compile(r'\+?[0-9]{10,15}')

# ---------- Извлечение данных ----------
def extract_name(text):
    text = re.sub(r'\s+', ' ', text).strip()
    patterns = [
        r'(?:меня зовут|зовут|мое имя|имя)\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)',
        r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s+(?:на связи|на линии)',
        r'^([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)[,\s]',
        r'^([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)$',
        r'([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*[—–-]',
        r'[—–-]\s*([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None

def extract_company(text, name_already_known=False):
    patterns = [
        r'(?:компания|фирма|организация|ооо|ип|зао|ао)\s+([А-ЯЁ][А-ЯЁа-яё\s]+?)(?:\s|\.|,|$|и)',
        r'([А-ЯЁ][А-ЯЁа-яё\s]{2,}?)\s+(?:компания|фирма)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    if name_already_known:
        words = text.strip().split()
        if len(words) == 1 and words[0][0].isupper():
            return words[0]
    return None

def extract_industry(text):
    keywords = ['торговля', 'продажи', 'логистика', 'медицина', 'образование',
                'строительство', 'производство', 'услуги', 'ритейл', 'e-commerce']
    for word in keywords:
        if word in text.lower():
            return word
    match = re.search(r'(?:сфера|область|отрасль)\s+([а-яё\s]+?)(?:\s|\.|,|$)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None
# ------------------------------------------------

user_sessions = defaultdict(lambda: {
    "stage": "initial",
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
        logger.info(f"✅ Имя извлечено: {extracted_name}")

    name_known = session["collected"].get("name") is not None
    extracted_company = extract_company(user_message, name_known)
    if extracted_company and not session["collected"].get("company"):
        session["collected"]["company"] = extracted_company
        logger.info(f"✅ Компания извлечена: {extracted_company}")

    extracted_industry = extract_industry(user_message)
    if extracted_industry and not session["collected"].get("industry"):
        session["collected"]["industry"] = extracted_industry
        logger.info(f"✅ Сфера извлечена: {extracted_industry}")
    # -------------------------

    # Проверка номера телефона
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

        logger.info(f"💾 Попытка сохранить лида: phone={phone}, name={name}, company={company}")
        logger.info(f"Calling save_lead with phone={phone}")

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
            logger.info("✅ save_lead выполнен успешно")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения лида: {e}", exc_info=True)

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

    # Управление стадиями
    system_extra = ""

    if session["stage"] == "initial":
        if missing:
            session["stage"] = "gathering_info"
            if not collected.get("name"):
                system_extra = "Твоя задача: спросить имя клиента. Не пиши ничего, кроме вопроса об имени. Не рассказывай о компании, не давай справок, не предлагай услуги."
            elif not collected.get("company"):
                system_extra = "Твоя задача: спросить название компании клиента. Не добавляй ничего лишнего."
            elif not collected.get("industry"):
                system_extra = "Твоя задача: спросить сферу деятельности компании. Только вопрос."
        else:
            session["stage"] = "collecting_pain"
            system_extra = known_info_str + "Все данные о клиенте собраны. Теперь выясни его потребность (боль). Задай открытый вопрос, например: 'Расскажите подробнее, с какими трудностями вы сталкиваетесь в обработке заявок?' Не предлагай услуги."

    elif session["stage"] == "gathering_info":
        if missing:
            next_field = missing[0]
            if next_field == "имя":
                system_extra = known_info_str + "Спроси имя клиента, если оно ещё неизвестно. Только вопрос."
            elif next_field == "название компании":
                system_extra = known_info_str + "Спроси название компании клиента. Только вопрос."
            elif next_field == "сфера деятельности":
                system_extra = known_info_str + "Спроси сферу деятельности компании. Только вопрос."
        else:
            session["stage"] = "collecting_pain"
            system_extra = known_info_str + "Все данные собраны. Выясни потребность клиента."

    elif session["stage"] == "collecting_pain":
        if not collected.get("pain"):
            system_extra = known_info_str + "Ты сейчас на этапе выяснения проблемы клиента. Задай уточняющий вопрос о его бизнесе, чтобы понять его потребности. Не предлагай консультацию."
        else:
            session["stage"] = "offer_consultation"
            system_extra = known_info_str + "Ты уже выяснил проблему клиента. Предложи бесплатную консультацию и попроси номер телефона и удобное время. Не задавай больше вопросов."

    elif session["stage"] == "offer_consultation":
        system_extra = known_info_str + "Предложи бесплатную консультацию и попроси номер телефона и удобное время. Не пиши ничего другого."

    elif session["stage"] == "completed":
        system_extra = known_info_str + "Диалог завершён, консультация назначена. Отвечай на вопросы клиента, используя известные данные. Не предлагай больше консультаций."

    # Формируем context_info
    context_info = {
        "stage": session["stage"],
        "greeted": session.get("greeted", False),
        "collected": collected
    }

    logger.info(f"stage={session['stage']}, missing={missing}, known={known_info_parts}")
    logger.info(f"system_extra: {system_extra}")

    try:
        # Используем асинхронный HTTP-клиент вместо requests
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "user_id": USER_ID,
                "message": user_message,
                "use_rag": False,  # отключаем RAG для отладки, потом можно включить
                "system_extra": system_extra,
                "context_info": json.dumps(context_info, ensure_ascii=False)
            }
            response = await client.post(
                API_URL,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            data = response.json()
            reply = data.get("reply", "⚠️ Не удалось получить ответ.")
    except Exception as e:
        logger.error(f"Ошибка вызова API: {e}", exc_info=True)
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