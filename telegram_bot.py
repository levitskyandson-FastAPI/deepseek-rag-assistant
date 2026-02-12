import os
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests
import nest_asyncio
nest_asyncio.apply()

load_dotenv()

# Токены и ключи
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# Системный промпт для твоего агентства
SYSTEM_PROMPT = """
Ты — официальный ИИ-ассистент агентства Levitsky & Son AI Solutions.
Мы создаем корпоративных ИИ-помощников для бизнеса на базе DeepSeek.
Твоя задача — вежливо и профессионально отвечать на вопросы клиентов о наших услугах.
Если не знаешь ответа — честно скажи, что уточнишь у специалиста.
Отвечай на том же языке, на котором к тебе обратились (русский/английский).
Будь дружелюбным, но деловым.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ на команду /start"""
    await update.message.reply_text(
        "👋 Добро пожаловать в Levitsky & Son AI Solutions!\n\n"
        "Я — ваш ИИ-консультант. Можете спросить меня о наших услугах, "
        "стоимости разработки ассистентов или примерах внедрений.\n\n"
        "Чем могу помочь?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений пользователя через DeepSeek"""
    user_message = update.message.text
    user_name = update.message.from_user.first_name
    
    # Показываем "печатает..."
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, 
        action="typing"
    )
    
    try:
        # Запрос к DeepSeek API
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.7,
            "max_tokens": 1000
        }
        
        response = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        ai_response = response.json()["choices"][0]["message"]["content"]
        
        # Отправляем ответ в Telegram
        await update.message.reply_text(ai_response)
        
    except Exception as e:
        error_msg = f"❌ Произошла ошибка при обращении к ИИ: {str(e)}"
        await update.message.reply_text(error_msg)

async def main():
    """Запуск бота"""
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 Telegram Bot запущен и готов к работе!")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
import datetime

LOG_FILE = "bot_requests.log"

def log_interaction(user_id, user_name, user_message, ai_response):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"\n[{timestamp}] USER {user_id} ({user_name}): {user_message}\n")
        f.write(f"[{timestamp}] BOT: {ai_response}\n")
        f.write("-" * 80 + "\n")