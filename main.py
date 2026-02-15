import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from routers.chat import router as chat_router
from routers.documents import router as documents_router
from core.logger import setup_logger
from config import settings
from telegram_bot import start, handle_message  # импортируем функции бота

logger = setup_logger(settings.log_level)

# --- Telegram Bot setup ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set in environment variables")

telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# --- Lifespan для установки/удаления webhook ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Запуск DeepSeek RAG Assistant...")
    logger.info(f"📚 Модель чата: {settings.chat_model}")
    logger.info(f"🧠 Режим RAG: активен")

    # Устанавливаем webhook для Telegram бота
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        logger.error("WEBHOOK_URL not set. Bot will not receive updates.")
    else:
        try:
            await telegram_app.bot.set_webhook(url=webhook_url)
            logger.info(f"✅ Webhook установлен на {webhook_url}")
        except Exception as e:
            logger.error(f"❌ Ошибка установки webhook: {e}")

    yield

    # Shutdown
    await telegram_app.bot.delete_webhook()
    logger.info("🛑 Остановка приложения...")

# --- FastAPI app ---
app = FastAPI(
    title="Levitsky & Son AI Solutions — DeepSeek RAG",
    description="Корпоративный ИИ-ассистент на базе DeepSeek с RAG и Telegram webhook",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры FastAPI
app.include_router(chat_router)
app.include_router(documents_router)

# Эндпоинт для получения обновлений от Telegram
@app.post("/webhook")
async def webhook(request: Request):
    json_data = await request.json()
    update = Update.de_json(json_data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

# Корневой эндпоинт для проверки
@app.get("/")
async def root():
    return {
        "service": "DeepSeek RAG Assistant",
        "status": "operational",
        "agency": "Levitsky & Son AI Solutions"
    }

# Эндпоинт для health check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "model": settings.chat_model}