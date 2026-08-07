from typing import List, Optional, Dict
from pydantic import BaseModel, Field

class InlineAttachment(BaseModel):
    filename: str
    mime_type: str
    data: str  # Base64 encoded content

class ChatRequest(BaseModel):
    question: str = Field(..., description="User question")
    session_id: Optional[str] = Field("default", description="Session ID for chat history")
    eli5_mode: bool = Field(False, description="Explain Like I'm 5 simplified mode")
    attachments: List[InlineAttachment] = Field([], description="Inline files for context")


class SourceDocument(BaseModel):
    page_number: int
    filename: str
    snippet: str

class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceDocument] = []
    confidence_score: float = 0.0
    follow_up_suggestions: List[str] = []

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

class FileDetail(BaseModel):
    filename: str
    size_bytes: int = 0
    page_count: int = 0
    chunk_count: int = 0
    upload_time: float = 0.0

class StatusResponse(BaseModel):
    is_ready: bool
    total_chunks: int
    filenames: List[str]
    is_processing: bool = False
    file_details: List[FileDetail] = []
    total_indexing_time: float = 0.0
    avg_chunk_size: float = 0.0

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

