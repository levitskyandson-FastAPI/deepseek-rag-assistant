import os
import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from routers.chat import router as chat_router
from routers.documents import router as documents_router
from routers.avito import router as avito_router            # ← добавлено
from core.logger import setup_logger
from config import settings
from telegram_bot import start, handle_message


# Импорт для работы с PostgreSQL
from services.db import init_db_pool, close_db_pool, get_all_active_clients

# Импорт воркера Avito (файл avito_worker.py в корне)
from avito_worker import avito_worker_loop                  # ← добавлено

logger = setup_logger(settings.log_level)

# ======================================================
# GLOBAL EXCEPTION HANDLER FOR ASYNCIO
# ======================================================

def handle_asyncio_exception(loop, context):
    msg = context.get("exception", context["message"])
    logger.error(f"🔥 Unhandled exception in event loop: {msg}", exc_info=context.get("exception"))

loop = asyncio.get_event_loop()
loop.set_exception_handler(handle_asyncio_exception)


# ======================================================
# SIGNAL HANDLERS
# ======================================================

def signal_handler(sig, frame):
    logger.info(f"📡 Received signal {sig} ({signal.Signals(sig).name}), shutting down gracefully...")
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# ======================================================
# Глобальный словарь приложений Telegram-ботов
# ======================================================
telegram_apps = {}


# ======================================================
# LIFESPAN
# ======================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Запуск DeepSeek RAG Assistant...")
    logger.info(f"📚 Модель чата: {settings.chat_model}")
    logger.info("🧠 Режим RAG: активен")

    # 1. Инициализация пула соединений с PostgreSQL
    await init_db_pool()

    # 2. Запуск фонового воркера Avito
    asyncio.create_task(avito_worker_loop())                # ← добавлено

    # 3. Загрузка активных клиентов из БД
    clients = await get_all_active_clients()
    if not clients:
        logger.warning("⚠️ Нет активных клиентов в таблице clients")
    else:
        for c in clients:
            token = c.get("bot_token")
            client_id = c.get("id")
            if not token or not client_id:
                logger.warning("⚠️ Пропуск клиента: нет bot_token или id")
                continue

            tg_app = Application.builder().token(token).build()
            tg_app.bot_data["client_id"] = client_id
            tg_app.add_handler(CommandHandler("start", start))
            tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

            telegram_apps[token] = tg_app

    logger.info(f"🤖 Загружено Telegram ботов: {len(telegram_apps)}")

    # 4. Установка вебхуков
    webhook_base = os.getenv("WEBHOOK_URL_BASE")
    if not webhook_base:
        logger.error("❌ WEBHOOK_URL_BASE not set")
    else:
        for token, tg_app in telegram_apps.items():
            try:
                await tg_app.initialize()
                await tg_app.start()
                await tg_app.bot.set_webhook(
                    url=f"{webhook_base}/webhook/{token}",
                    drop_pending_updates=True
                )
                logger.info(f"✅ Webhook установлен для клиента {tg_app.bot_data.get('client_id')} ({token[:8]}...)")
            except Exception as e:
                logger.error(f"❌ Ошибка webhook для {token[:8]}: {e}")

    yield

    # 5. Корректное завершение
    logger.info("🛑 Lifespan shutdown started...")
    for token, tg_app in telegram_apps.items():
        try:
            await tg_app.bot.delete_webhook()
            await tg_app.stop()
            await tg_app.shutdown()
        except Exception as e:
            logger.error(f"Ошибка shutdown для {token[:8]}: {e}")

    await close_db_pool()
    logger.info("✅ Lifespan shutdown completed")


# ======================================================
# FASTAPI
# ======================================================

app = FastAPI(
    title="Levitsky & Son AI Solutions — DeepSeek RAG SaaS",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(avito_router)        # ← добавлено


# ======================================================
# TELEGRAM WEBHOOK ROUTING
# ======================================================

@app.post("/webhook/{token}")
async def webhook(token: str, request: Request):
    if token not in telegram_apps:
        logger.warning("❌ Unknown bot token in webhook")
        return {"ok": False}

    try:
        json_data = await request.json()
        tg_app = telegram_apps[token]
        update = Update.de_json(json_data, tg_app.bot)
        await tg_app.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


# ======================================================
# SYSTEM ENDPOINTS
# ======================================================

@app.api_route("/", methods=["GET", "HEAD"])
async def index():
    return {"status": "ok", "message": "DeepSeek RAG Assistant is running"}

@app.api_route("/health", methods=["GET", "HEAD"])
async def health_check():
    return {
        "status": "healthy",
        "model": settings.chat_model,
        "bots_loaded": len(telegram_apps),
    }