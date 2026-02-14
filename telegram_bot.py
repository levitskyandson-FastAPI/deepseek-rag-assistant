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

# Словарь для хранения сессий пользователей
user_sessions = defaultdict(lambda: {
    "stage": "initial",        # initial, clarifying, offer_consultation, collecting_contact, completed
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

    # Проверка на номер телефона
    phone_match = PHONE_REGEX.search(user_message)
    if phone_match and session["stage"] != "completed":
        phone = phone_match.group()
        name = session["collected"].get("name")
        pain = session["collected"].get("pain")

        # Сохраняем лида в Supabase
        try:
            await save_lead(
                telegram_user_id=user_id,
                name=name,
                phone=phone,
                pain=pain,
                extra_data={"source": "telegram_bot", "stage": session["stage"]}
            )
        except Exception as e:
            print(f"Ошибка сохранения лида: {e}")

        session["collected"]["phone"] = phone
        session["stage"] = "completed"
        reply = "Спасибо! Я передал ваш номер менеджеру. Он свяжется с вами в ближайшее время для согласования удобного времени консультации."
        session["greeted"] = True
        await update.message.reply_text(reply)
        return

    # Определяем стадию и системные инструкции
    system_extra = ""
    if session["stage"] == "initial":
        # Начальная стадия – выясняем потребность
        system_extra = (
            "Ты — продающий консультант. Клиент только начал разговор. "
            "Твоя задача — выяснить его потребность (боль). Задавай открытые вопросы: "
            "'Расскажите подробнее о вашей задаче?', 'С какими трудностями вы сталкиваетесь?'. "
            "Не предлагай консультацию сразу. Не задавай слишком много вопросов подряд."
        )
        # После получения развёрнутого ответа (больше 20 символов) переходим в clarifying
        if len(user_message) > 20:
            session["stage"] = "clarifying"
            # Сохраняем первое описание как боль
            session["collected"]["pain"] = user_message

    elif session["stage"] == "clarifying":
        # Уточняем детали, но не больше 1-2 вопросов
        system_extra = (
            "Ты уже получил общее описание проблемы. Теперь задай 1-2 уточняющих вопроса, "
            "чтобы лучше понять ситуацию (например, объём заявок, текущие проблемы). "
            "После ответа клиента (или если ответ короткий) переходи к предложению бесплатной консультации."
        )
        # После ответа пользователя (любого) переходим к предложению консультации
        session["stage"] = "offer_consultation"

    elif session["stage"] == "offer_consultation":
        system_extra = (
            "Ты уже выяснил проблему клиента. Теперь нужно предложить бесплатную консультацию. "
            "Попроси его выбрать удобное время и оставить номер телефона. "
            "Например: 'Для более точного расчёта и демонстрации возможностей я предлагаю вам бесплатную консультацию с нашим техническим специалистом. Выберите, пожалуйста, удобное время для звонка (сегодня или завтра) и оставьте ваш номер телефона.'"
        )

    elif session["stage"] == "collecting_contact":
        system_extra = "Клиент согласился на консультацию. Вежливо попроси оставить номер телефона, если он ещё не оставил."

    else:
        system_extra = "Ответь на вопрос клиента максимально полезно."

    # Формируем context_info для передачи в API
    context_info = {
        "stage": session["stage"],
        "greeted": session.get("greeted", False),
        "collected": session["collected"]
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

    # После первого ответа помечаем, что поздоровались
    if not session["greeted"]:
        session["greeted"] = True

    # Если в ответе есть просьба оставить номер, переводим в collecting_contact (если ещё не там)
    if "оставьте ваш номер" in reply and session["stage"] not in ("collecting_contact", "completed"):
        session["stage"] = "collecting_contact"

    await update.message.reply_text(reply)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Telegram Bot запущен и готов к работе!")
    app.run_polling()

if __name__ == "__main__":
    main()