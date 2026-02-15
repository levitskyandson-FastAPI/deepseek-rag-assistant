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

API_URL = os.getenv("API_URL", "https://deepseek-rag-assistant.onrender.com/chat/")
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
    """
    Временно упрощённая версия – отвечает на любое сообщение.
    Позже сюда можно вернуть всю логику сбора данных.
    """
    try:
        user_message = update.message.text
        logger.info(f"Получено сообщение: {user_message}")
        
        # Простой ответ для проверки
        reply = "Привет! Я услышал ваше сообщение. (это тестовый ответ)"
        
        await update.message.reply_text(reply)
        logger.info("Ответ отправлен")
    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}", exc_info=True)
        await update.message.reply_text("Извините, произошла внутренняя ошибка.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Telegram Bot запущен и готов к работе!")
    app.run_polling()

if __name__ == "__main__":
    main()