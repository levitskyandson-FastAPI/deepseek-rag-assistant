from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

# ---------- Chat ----------
class ChatRequest(BaseModel):
    user_id: str
    message: str
    use_rag: bool = True
    system_extra: Optional[str] = None          # дополнительная инструкция для модели
    context_info: Optional[str] = None           # JSON-строка с состоянием диалога

class ChatResponse(BaseModel):
    reply: str
    sources: List[str] = Field(default_factory=list)
    new_state: Optional[Dict[str, Any]] = None   # если нужно обновить состояние

# ---------- Documents ----------
class DocumentUploadResponse(BaseModel):
    filename: str
    chunks: int
    status: str

# ---------- Health ----------
class HealthResponse(BaseModel):
    status: str
    model: str