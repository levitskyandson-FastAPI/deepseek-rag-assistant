import os
import asyncio
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Разрешаем вложенные циклы событий (для совместимости с некоторыми средами)
import nest_asyncio
nest_asyncio.apply()

load_dotenv()

# Токен бота из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# URL вашего FastAPI-сервиса (Web Service)
API_URL = "https://deepseek-rag-assistant-1-ldph.onrender.com/chat/"

# Фиксированный user_id, под которым загружены документы
USER_ID = "levitsky_agency"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ на команду /start"""
    await update.message.reply_text(
        "👋 Добро пожаловать в Levitsky & Son AI Solutions!\n\n"
        "Я — ваш ИИ-консультант. Можете спросить меня о наших услугах, "
        "стоимости разработки ассистентов или примерах внедрений.\n\n"
        "Чем могу помочь?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений – отправка запроса к FastAPI с RAG"""
    user_message = update.message.text
    user_name = update.message.from_user.first_name

    # Показываем индикатор "печатает..."
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:
        # Формируем запрос к API
        payload = {
            "user_id": USER_ID,           # фиксированный ID для теста
            "message": user_message,
            "use_rag": True                # обязательно включаем RAG
        }
        headers = {"Content-Type": "application/json"}

        # Логируем отправляемый запрос (для отладки)
        print(f"➡️ Отправка запроса к API: {payload}")

        response = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        reply = data.get("reply", "⚠️ Не удалось получить ответ.")
        sources = data.get("sources", [])

        await update.message.reply_text(reply)

    except requests.exceptions.Timeout:
        await update.message.reply_text("⏳ Сервер не отвечает. Попробуйте позже.")
    except requests.exceptions.RequestException as e:
        error_msg = f"❌ Ошибка при обращении к серверу: {str(e)}"
        print(error_msg)
        await update.message.reply_text(error_msg)
    except Exception as e:
        error_msg = f"❌ Неизвестная ошибка: {str(e)}"
        print(error_msg)
        await update.message.reply_text(error_msg)

def main():
    """Запуск бота"""
    # Создаём приложение
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Добавляем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Telegram Bot запущен и готов к работе!")
    # Запускаем поллинг (блокирующий вызов)
    app.run_polling()

if __name__ == "__main__":
    main()