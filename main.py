import os
import asyncio
import signal
import sys
import tempfile
from contextlib import asynccontextmanager

import numpy as np
import scipy.io.wavfile as wavfile
from pydub import AudioSegment
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from routers.chat import router as chat_router
from routers.documents import router as documents_router
from routers.avito import router as avito_router
from core.logger import setup_logger
from config import settings
from telegram_bot import start, handle_message

# Импорт для работы с PostgreSQL
from services.db import init_db_pool, close_db_pool, get_all_active_clients

# Импорт воркера Avito
from avito_worker import avito_worker_loop

# ---------- Импорты для голосового распознавания (T-one) ----------
from tone import StreamingCTCPipeline, read_audio

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
# Глобальная модель STT (T-one) – общая для всех ботов
# ======================================================
asr_pipeline = None

def init_stt_model():
    global asr_pipeline
    if asr_pipeline is None:
        logger.info("🎤 Загрузка модели T-one...")
        asr_pipeline = StreamingCTCPipeline.from_hugging_face()
        logger.info("✅ Модель T-one загружена и готова к работе")
    return asr_pipeline

# ======================================================
# Обработчик голосовых сообщений
# ======================================================
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("🎤 Получено голосовое сообщение")
    voice = update.message.voice
    file = await voice.get_file()

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_ogg:
        ogg_path = tmp_ogg.name
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
        wav_path = tmp_wav.name

    try:
        await file.download_to_drive(ogg_path)
        logger.info(f"📁 OGG файл скачан, размер: {os.path.getsize(ogg_path)} байт")

        audio = AudioSegment.from_ogg(ogg_path)
        duration_sec = len(audio) / 1000.0
        logger.info(f"⏱️ Длительность аудио: {duration_sec:.2f} сек")

        audio = audio.set_frame_rate(16000).set_channels(1)
        audio.export(wav_path, format="wav")
        logger.info(f"📊 WAV файл создан, размер: {os.path.getsize(wav_path)} байт")

        # Используем встроенную функцию T-one для чтения аудио
        audio_array = read_audio(wav_path)

        model = init_stt_model()
        result = model.forward_offline(audio_array)
        full_text = " ".join([phrase.text for phrase in result])

        logger.info(f"📝 Распознанный текст: '{full_text}'")

        if full_text.strip():
            await update.message.reply_text(f"🎤 Распознано: {full_text}")
        else:
            await update.message.reply_text("🤔 Не удалось распознать речь. Попробуйте говорить чётче.")

    except Exception as e:
        logger.exception(f"Ошибка обработки голоса: {e}")
        await update.message.reply_text("Извините, не удалось распознать голосовое сообщение. Попробуйте отправить текст.")
    finally:
        os.unlink(ogg_path)
        os.unlink(wav_path)

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
    asyncio.create_task(avito_worker_loop())

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
            # Добавляем обработчик голосовых сообщений
            tg_app.add_handler(MessageHandler(filters.VOICE, handle_voice))

            telegram_apps[token] = tg_app

    logger.info(f"🤖 Загружено Telegram ботов: {len(telegram_apps)}")

    # 4. Предварительная инициализация модели STT (загружается один раз)
    init_stt_model()

    # 5. Установка вебхуков
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

    # 6. Корректное завершение
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
app.include_router(avito_router)

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