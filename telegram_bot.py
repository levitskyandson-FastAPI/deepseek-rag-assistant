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
USER_ID = "levitsky_agency"  # фиксированный для теста

# Хранилище состояний пользователей
user_sessions = defaultdict(lambda: {
    "stage": "initial",        # initial, clarifying, collecting_contact, completed
    "collected": {}            # name, phone, pain
})

# Регулярка для поиска телефона (простая)
PHONE_REGEX = re.compile(r'\+?[0-9]{10,15}')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = {"stage": "initial", "collected": {}}
    await update.message.reply_text(
        "👋 Добро пожаловать в Levitsky & Son AI Solutions!\n\n"
        "Я — ваш ИИ-ассистент. Расскажите, какая у вас задача, и я помогу подобрать решение."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    session = user_sessions[user_id]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # 1. Проверяем, не содержит ли сообщение телефон
    phone_match = PHONE_REGEX.search(user_message)
    if phone_match and session["stage"] != "completed":
        # Пользователь оставил телефон – сохраняем и переходим в финальную стадию
        session["collected"]["phone"] = phone_match.group()
        session["stage"] = "collecting_contact"
        # В этом случае не отправляем запрос к DeepSeek, а просто благодарим
        reply = "Спасибо! Я передал ваш номер менеджеру. Он свяжется с вами в ближайшее время."
        session["stage"] = "completed"
        await update.message.reply_text(reply)
        return

    # 2. Определяем дополнительные инструкции в зависимости от стадии
    system_extra = ""
    context_info = json.dumps(session, ensure_ascii=False)

    if session["stage"] == "initial":
        system_extra = (
            "Ты — продающий консультант. Клиент только начал разговор. "
            "Твоя задача — выяснить его потребность ('боль'). Задавай открытые вопросы: "
            "'Расскажите подробнее о вашей задаче?', 'С какими трудностями вы сталкиваетесь?'. "
            "Не предлагай консультацию сразу, сначала узнай, что ему нужно."
        )
    elif session["stage"] == "clarifying":
        system_extra = (
            "Ты уже немного поговорил с клиентом. Теперь нужно понять, готов ли он к звонку менеджера. "
            "Если он проявляет явный интерес (спрашивает цены, сроки, примеры), предложи: "
            "'Если хотите обсудить детали подробнее, наш специалист может перезвонить вам. Оставьте номер телефона.' "
            "Не спрашивай одно и то же много раз."
        )
    elif session["stage"] == "collecting_contact":
        system_extra = (
            "Клиент согласился на консультацию. Вежливо попроси оставить номер телефона. "
            "Если он уже оставил номер, поблагодари и скажи, что менеджер свяжется."
        )
    else:
        system_extra = "Ответь на вопрос клиента максимально полезно."

    # 3. Вызываем API с дополнительными инструкциями
    try:
        payload = {
            "user_id": USER_ID,
            "message": user_message,
            "use_rag": True,
            "system_extra": system_extra,
            "context_info": context_info
        }
        headers = {"Content-Type": "application/json"}
        response = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        reply = data.get("reply", "⚠️ Не удалось получить ответ.")
    except Exception as e:
        reply = f"❌ Ошибка: {e}"

    # 4. Анализируем ответ и обновляем состояние (простая эвристика)
    # Если в ответе бота есть просьба оставить телефон и мы ещё не в этой стадии, переходим в clarifying
    if "оставьте ваш номер" in reply and session["stage"] == "initial":
        session["stage"] = "clarifying"
    # Если в ответе бота есть "менеджер свяжется", значит, контакт получен
    if "менеджер свяжется" in reply and session["stage"] != "completed":
        session["stage"] = "completed"

    await update.message.reply_text(reply)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Telegram Bot запущен и готов к работе!")
    app.run_polling()

if __name__ == "__main__":
    main()