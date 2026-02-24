import asyncio
from typing import List

from services.supabase import supabase
from services.embeddings import get_embedding, split_text
from core.logger import logger


BUCKET_NAME = "client_docs"


async def ingest_client_folder(client_id: str, folder_name: str) -> int:
    """
    Ingest всех файлов из папки клиента в Storage.
    - скачивает файлы
    - режет на чанки
    - создаёт embedding
    - сохраняет в documents с client_id
    """
    # 🔥 Production-safe: очищаем старые документы клиента

    logger.info(f"🚀 Начинаем ingest для client_id={client_id}, folder={folder_name}")

    logger.info(f"🧹 Удаляем старые документы client_id={client_id}")
    supabase.table("documents").delete().eq("client_id", client_id).execute()

    # 1️⃣ Получаем список файлов
    files = supabase.storage.from_(BUCKET_NAME).list(folder_name)

    if not files:
        logger.warning("❌ В папке нет файлов")
        return 0

    total_chunks = 0

    for file in files:
        filename = file.get("name")
        if not filename:
            continue

        path = f"{folder_name}/{filename}"
        logger.info(f"📄 Обрабатываем файл: {path}")

        try:
            # 2️⃣ Скачиваем файл из Storage
            file_bytes = supabase.storage.from_(BUCKET_NAME).download(path)
            text = file_bytes.decode("utf-8")

            if not text.strip():
                logger.warning(f"⚠ Файл {filename} пустой")
                continue

            # 3️⃣ Чанкинг
            chunks = split_text(text)
            logger.info(f"{filename} → {len(chunks)} чанков")

            # 4️⃣ Для каждого чанка создаём embedding и сохраняем
            for i, chunk in enumerate(chunks):
                embedding = await get_embedding(chunk)

                data = {
                    "content": chunk,
                    "metadata": {
                        "filename": filename,
                        "folder": folder_name,
                        "chunk_index": i,
                        "chunk_size": len(chunk),
                    },
                    "embedding": embedding,
                    "client_id": client_id,
                }

                supabase.table("documents").insert(data).execute()

                total_chunks += 1

        except Exception as e:
            logger.error(
                f"❌ Ошибка при обработке файла {filename}: {e}",
                exc_info=True,
            )

    logger.info(f"✅ Ingest завершён. Всего сохранено чанков: {total_chunks}")
    return total_chunks