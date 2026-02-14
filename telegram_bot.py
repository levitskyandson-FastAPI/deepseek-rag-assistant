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

        # --- НОВЫЙ БЛОК: извлечение даты и времени ---
        preferred_date = None
        msg_lower = user_message.lower()
        if "сегодня" in msg_lower:
            preferred_date = "сегодня"
        elif "завтра" in msg_lower:
            preferred_date = "завтра"
        elif "послезавтра" in msg_lower:
            preferred_date = "послезавтра"

        # Ищем время в формате ЧЧ:ММ, ЧЧ-ММ, ЧЧ.ММ
        time_match = re.search(r'(\d{1,2})[:–-.](\d{2})', user_message)
        if not time_match:
            # Ищем просто час после предлога "в"
            time_match = re.search(r'в\s+(\d{1,2})(?:\s|$)', user_message)
        if time_match:
            hour = time_match.group(1)
            minute = time_match.group(2) if len(time_match.groups()) > 1 else "00"
            time_str = f"{hour}:{minute}"
            if preferred_date:
                preferred_date = f"{preferred_date} в {time_str}"
            else:
                preferred_date = time_str
        # --------------------------------------------

        # Сохраняем лида
        try:
            await save_lead(
                telegram_user_id=user_id,
                name=name,
                phone=phone,
                pain=pain,
                preferred_date=preferred_date,
                extra_data={"source": "telegram_bot", "stage": session["stage"]}
            )
        except Exception as e:
            print(f"Ошибка сохранения лида: {e}")

        session["collected"]["phone"] = phone
        session["stage"] = "completed"

        # Персонализированный ответ
        reply = "Спасибо! Я передал ваш номер менеджеру. "
        if preferred_date:
            reply += f"Вы выбрали {preferred_date}. "
        reply += "Он свяжется с вами в ближайшее время для согласования удобного времени консультации."

        session["greeted"] = True
        await update.message.reply_text(reply)
        return

    # Определяем стадию и системные инструкции
    system_extra = ""
    if session["stage"] == "initial":
        system_extra = (
            "Ты — продающий консультант. Клиент только начал разговор. "
            "Твоя задача — выяснить его потребность (боль). Задавай открытые вопросы: "
            "'Расскажите подробнее о вашей задаче?', 'С какими трудностями вы сталкиваетесь?'. "
            "Не предлагай консультацию сразу. Не задавай слишком много вопросов подряд."
        )
        if len(user_message) > 20:
            session["stage"] = "clarifying"
            session["collected"]["pain"] = user_message

    elif session["stage"] == "clarifying":
        system_extra = (
            "Ты уже получил общее описание проблемы. Теперь задай 1-2 уточняющих вопроса, "
            "чтобы лучше понять ситуацию (например, объём заявок, текущие проблемы). "
            "После ответа клиента (или если ответ короткий) переходи к предложению бесплатной консультации."
        )
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

    # Формируем context_info
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

    if not session["greeted"]:
        session["greeted"] = True

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