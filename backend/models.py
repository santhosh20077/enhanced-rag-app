from typing import List, Optional
from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    question: str = Field(..., description="User question")
    session_id: Optional[str] = Field("default", description="Session ID for chat history")
    api_key: Optional[str] = Field(None, description="Optional override for NVIDIA API Key")

class SourceDocument(BaseModel):
    page_number: int
    filename: str
    snippet: str

class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceDocument] = []

class UploadResponse(BaseModel):
    message: str
    task_id: str
    files_accepted: int

class ProcessingProgress(BaseModel):
    task_id: str
    status: str  # "parsing", "chunking", "embedding", "saving", "complete", "error"
    progress: float  # 0.0 to 1.0
    stage_label: str  # human-readable stage name
    files_total: int
    pages_extracted: int
    chunks_created: int
    elapsed_seconds: float
    error: Optional[str] = None

class StatusResponse(BaseModel):
    is_ready: bool
    total_chunks: int
    filenames: List[str]
    is_processing: bool = False

class AuthUser(BaseModel):
    user_id: str
    name: str
    email: str
    picture: Optional[str] = None

class AuthVerifyRequest(BaseModel):
    credential: str = Field(..., description="Google ID Token credential")

class AuthVerifyResponse(BaseModel):
    authenticated: bool
    user: Optional[AuthUser] = None
    message: str = "Success"

