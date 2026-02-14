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

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_URL = "https://deepseek-rag-assistant-1-ldph.onrender.com/chat/"
USER_ID = "levitsky_agency"

PHONE_REGEX = re.compile(r'\+?[0-9]{10,15}')

user_sessions = defaultdict(lambda: {
    "stage": "initial",
    "greeted": False,
    "collected": {}
})

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = {
        "stage": "initial",
        "greeted": True,  # сразу после /start считаем, что поздоровались
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

    # Проверка на номер телефона
    phone_match = PHONE_REGEX.search(user_message)
    if phone_match and session["stage"] != "completed":
        session["collected"]["phone"] = phone_match.group()
        session["stage"] = "completed"
        # Здесь можно добавить вызов CRM
        reply = "Спасибо! Я передал ваш номер менеджеру. Он свяжется с вами в ближайшее время."
        session["greeted"] = True
        await update.message.reply_text(reply)
        return

    # Формируем context_info для передачи
    context_info = {
        "stage": session["stage"],
        "greeted": session["greeted"],
        "collected": session["collected"]
    }

    # Определяем system_extra в зависимости от стадии
    system_extra = ""
    if session["stage"] == "initial":
        system_extra = (
            "Ты — продающий консультант. Клиент только начал разговор. "
            "Твоя задача — выяснить его потребность. Задавай открытые вопросы: "
            "'Расскажите подробнее о вашей задаче?', 'С какими трудностями вы сталкиваетесь?'"
        )
    elif session["stage"] == "clarifying":
        system_extra = (
            "Ты уже немного поговорил с клиентом. Если он проявляет явный интерес (цены, сроки, примеры), "
            "предложи: 'Если хотите обсудить детали подробнее, наш специалист может перезвонить вам. Оставьте номер телефона.'"
        )
    elif session["stage"] == "collecting_contact":
        system_extra = "Клиент согласился на консультацию. Вежливо попроси оставить номер телефона."
    else:
        system_extra = "Ответь на вопрос клиента максимально полезно."

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

    # Обновляем состояние на основе ответа бота
    if "оставьте ваш номер" in reply and session["stage"] == "initial":
        session["stage"] = "clarifying"
    if "менеджер свяжется" in reply:
        session["stage"] = "completed"
    # После первого ответа бота считаем, что диалог идёт, greeted больше не нужно
    if not session["greeted"]:
        session["greeted"] = True

    await update.message.reply_text(reply)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Telegram Bot запущен и готов к работе!")
    app.run_polling()

if __name__ == "__main__":
    main()