import asyncio
import aiohttp
import asyncpg
from typing import List
import PyPDF2
from io import BytesIO
from tenacity import retry, stop_after_attempt, wait_exponential

from core.logger import logger
# Если есть settings, можно импортировать, но здесь используем прямые значения
# from config import settings
from config import settings
# ========== КОНФИГУРАЦИЯ (ваши данные) ==========
DB_PASSWORD = "kS8-i8t-XJg-eJD"
DB_HOST = "rc1b-f309n3otbdih0f46.mdb.yandexcloud.net"
DB_PORT = 6432
DB_NAME = "db1"
DB_USER = "user1"
DB_DSN = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?ssl=require"

YC_FOLDER_ID = settings.yc_folder_id
YC_API_KEY = settings.settings.settings.yc_api_key
EMBEDDING_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"
EMBEDDING_MODEL = "text-search-doc"  # для документов
# ==============================================

# Глобальный пул соединений
_pool = None

async def init_db_pool():
    global _pool
    _pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=10)
    logger.info("✅ Пул соединений с БД создан")

async def close_db_pool():
    if _pool:
        await _pool.close()
        logger.info("🔌 Пул соединений закрыт")

def get_db_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Пул БД не инициализирован")
    return _pool

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def get_embedding(text: str) -> List[float]:
    """Получение эмбеддинга через YandexGPT API"""
    headers = {
        "Authorization": f"Api-Key {YC_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "modelUri": f"emb://{YC_FOLDER_ID}/{EMBEDDING_MODEL}",
        "text": text
    }
    try:
        logger.info(f"Запрос эмбеддинга для текста длиной {len(text)}")
        async with aiohttp.ClientSession() as session:
            async with session.post(EMBEDDING_URL, headers=headers, json=payload, timeout=30) as resp:
                if resp.status != 200:
                    text_err = await resp.text()
                    logger.error(f"Ошибка YandexGPT API {resp.status}: {text_err}")
                    raise Exception(f"YandexGPT API error: {resp.status}")
                data = await resp.json()
                embedding = data["embedding"]
                logger.info(f"Получен эмбеддинг размерностью {len(embedding)}")
                return embedding
    except Exception as e:
        logger.error(f"Ошибка YandexGPT API: {e}", exc_info=True)
        raise

def split_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    """Разделение текста на чанки с перекрытием"""
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        end = min(start + chunk_size, text_length)
        if end < text_length:
            last_period = text.rfind('.', start, end)
            last_space = text.rfind(' ', start, end)
            cut_point = max(last_period, last_space)
            if cut_point > start:
                end = cut_point + 1
        chunks.append(text[start:end].strip())
        start = end - overlap if end < text_length else text_length
    
    return chunks

async def extract_text_from_file(file) -> str:
    """Извлечение текста из загруженного файла"""
    content = await file.read()
    
    if file.filename.endswith('.txt'):
        return content.decode('utf-8')
    elif file.filename.endswith('.pdf'):
        pdf_reader = PyPDF2.PdfReader(BytesIO(content))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        return text
    else:
        raise ValueError(f"Неподдерживаемый тип файла: {file.filename}")

async def process_document(client_id: str, file, metadata: dict) -> int:
    """
    Обработка документа: разбивка на чанки, генерация эмбеддингов, сохранение в PostgreSQL.
    client_id — UUID клиента (например, '112e1504-1724-4c46-9d1d-bb8fb4c5cffe')
    """
    pool = get_db_pool()
    try:
        logger.info(f"process_document: начало, файл {file.filename}")
        text = await extract_text_from_file(file)
        if not text.strip():
            logger.warning(f"Файл {file.filename} не содержит текста")
            return 0
        logger.info(f"Извлечён текст длиной {len(text)} символов")
        
        chunks = split_text(text)
        logger.info(f"Файл {file.filename} разбит на {len(chunks)} чанков")
        
        doc_metadata = {
            "filename": file.filename,
            "content_type": file.content_type,
            **metadata
        }
        
        success_count = 0
        async with pool.acquire() as conn:
            for i, chunk in enumerate(chunks):
                chunk_metadata = {
                    **doc_metadata,
                    "chunk_index": i,
                    "chunk_size": len(chunk)
                }
                try:
                    embedding = await get_embedding(chunk)
                    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
                    await conn.execute("""
                        INSERT INTO documents (content, metadata, embedding, client_id)
                        VALUES ($1, $2::jsonb, $3::vector, $4)
                    """, chunk, chunk_metadata, embedding_str, client_id)
                    success_count += 1
                except Exception as e:
                    logger.error(f"Ошибка при обработке чанка {i}: {e}")
        
        logger.info(f"Успешно сохранено {success_count} из {len(chunks)} чанков для {file.filename}")
        return success_count
    except Exception as e:
        logger.error(f"Критическая ошибка при обработке {file.filename}: {e}", exc_info=True)
        raise

async def update_missing_embeddings(client_id: str):
    """Обновляет эмбеддинги для документов, у которых они ещё не заполнены."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, content FROM documents
            WHERE client_id = $1 AND embedding IS NULL
        """, client_id)
    
    if not rows:
        logger.info(f"Нет документов для обновления у клиента {client_id}")
        return
    
    logger.info(f"Найдено документов для обновления: {len(rows)}")
    for row in rows:
        doc_id = row["id"]
        content = row["content"]
        try:
            embedding = await get_embedding(content)
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            async with pool.acquire() as conn:
                await conn.execute("""
                    UPDATE documents SET embedding = $1::vector WHERE id = $2
                """, embedding_str, doc_id)
            logger.info(f"Документ {doc_id} обновлён")
        except Exception as e:
            logger.error(f"Ошибка при обновлении документа {doc_id}: {e}")

# Для самостоятельного запуска обновления
async def main():
    await init_db_pool()
    # Укажите UUID вашего клиента (например, для Levitsky)
    client_id = "112e1504-1724-4c46-9d1d-bb8fb4c5cffe"
    await update_missing_embeddings(client_id)
    await close_db_pool()

if __name__ == "__main__":
    asyncio.run(main())