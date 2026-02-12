from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

# ---------- Chat ----------
class ChatRequest(BaseModel):
    user_id: str
    message: str
    use_rag: bool = True
    temperature: Optional[float] = 0.1

class ChatResponse(BaseModel):
    reply: str
    sources: List[str] = Field(default_factory=list)

# ---------- Documents ----------
class DocumentUploadResponse(BaseModel):
    filename: str
    chunks: int
    status: str

# ---------- Health ----------
class HealthResponse(BaseModel):
    status: str
    model: str