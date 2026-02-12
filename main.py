import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.chat import router as chat_router
from routers.documents import router as documents_router
from core.logger import setup_logger
from config import settings

logger = setup_logger(settings.log_level)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Запуск DeepSeek RAG Assistant...")
    logger.info(f"📚 Модель чата: {settings.chat_model}")
    logger.info(f"🧠 Режим RAG: активен")
    yield
    logger.info("🛑 Остановка приложения...")

app = FastAPI(
    title="Levitsky & Son AI Solutions — DeepSeek RAG",
    description="Корпоративный ИИ-ассистент на базе DeepSeek с RAG",
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

app.include_router(chat_router)
app.include_router(documents_router)

@app.get("/")
async def root():
    return {
        "service": "DeepSeek RAG Assistant",
        "status": "operational",
        "agency": "Levitsky & Son AI Solutions"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "model": settings.chat_model}
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)