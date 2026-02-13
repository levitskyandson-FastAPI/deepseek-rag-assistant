from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from services.embeddings import process_document
from core.logger import logger
import json
from typing import Optional

router = APIRouter(prefix="/documents", tags=["Documents"])

@router.post("/upload")
async def upload_document(
    user_id: str = Form(...),
    file: UploadFile = File(...),
    metadata: Optional[str] = Form("{}")
):
    try:
        logger.info(f"Начало загрузки файла: {file.filename}, user_id: {user_id}")
        
        # Проверяем, что файл не пустой
        if not file.filename:
            raise HTTPException(status_code=400, detail="Файл не выбран")
        
        # Парсим метаданные
        try:
            metadata_dict = json.loads(metadata)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга metadata: {e}")
            raise HTTPException(status_code=400, detail=f"Неверный формат JSON в metadata: {str(e)}")
        
        # Обрабатываем документ
        chunks = await process_document(user_id, file, metadata_dict)
        
        logger.info(f"Файл {file.filename} успешно загружен, создано {chunks} чанков")
        return {
            "status": "success",
            "filename": file.filename,
            "chunks": chunks
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Неожиданная ошибка при загрузке {file.filename}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера: {str(e)}")