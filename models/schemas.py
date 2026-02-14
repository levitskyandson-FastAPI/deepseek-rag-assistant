from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class ChatRequest(BaseModel):
    user_id: str
    message: str
    use_rag: bool = True
    system_extra: Optional[str] = None
    context_info: Optional[str] = None

class ChatResponse(BaseModel):
    reply: str
    sources: List[str] = Field(default_factory=list)
    new_state: Optional[Dict[str, Any]] = None

class DocumentUploadResponse(BaseModel):
    filename: str
    chunks: int
    status: str

class HealthResponse(BaseModel):
    status: str
    model: str