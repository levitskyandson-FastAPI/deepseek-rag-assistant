from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from services.embeddings import process_document
from typing import Optional
import json

router = APIRouter(prefix="/documents", tags=["Documents"])

@router.post("/upload")
async def upload_document(
    user_id: str = Form(...),
    file: UploadFile = File(...),
    metadata: Optional[str] = Form("{}")
):
    try:
        metadata_dict = json.loads(metadata)
        chunks = await process_document(user_id, file, metadata_dict)
        return {
            "status": "success",
            "filename": file.filename,
            "chunks": chunks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))