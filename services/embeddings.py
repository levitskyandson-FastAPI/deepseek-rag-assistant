import httpx
import asyncio
from config import settings
from services.supabase import supabase
from tenacity import retry, stop_after_attempt, wait_exponential
from fastapi import UploadFile
import PyPDF2
from io import BytesIO
from typing import List

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def get_embedding(text: str) -> List[float]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.deepseek_api_url}/embeddings",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json={"input": text, "model": settings.embedding_model}
        )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]

def split_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            last_period = text.rfind('.', start, end)
            if last_period > start:
                end = last_period + 1
        chunks.append(text[start:end].strip())
        start = end - overlap
    return chunks

async def extract_text_from_file(file: UploadFile) -> str:
    content = await file.read()
    if file.filename.endswith('.txt'):
        return content.decode('utf-8')
    elif file.filename.endswith('.pdf'):
        pdf = PyPDF2.PdfReader(BytesIO(content))
        return '\n'.join([page.extract_text() for page in pdf.pages])
    else:
        raise ValueError(f"Неподдерживаемый формат: {file.filename}")

async def process_document(user_id: str, file: UploadFile, metadata: dict) -> int:
    text = await extract_text_from_file(file)
    chunks = split_text(text)
    
    doc_metadata = {
        "user_id": user_id,
        "filename": file.filename,
        **metadata
    }
    
    tasks = []
    for i, chunk in enumerate(chunks):
        chunk_metadata = {**doc_metadata, "chunk_index": i}
        tasks.append(_save_chunk(chunk, chunk_metadata))
    
    results = await asyncio.gather(*tasks)
    return len(results)

async def _save_chunk(content: str, metadata: dict):
    embedding = await get_embedding(content)
    data = {"content": content, "metadata": metadata, "embedding": embedding}
    result = supabase.table("documents").insert(data).execute()
    return result.data[0]["id"]