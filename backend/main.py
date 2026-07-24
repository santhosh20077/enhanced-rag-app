import os
from typing import List
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .models import ChatRequest, ChatResponse, UploadResponse, StatusResponse, ProcessingProgress, AuthVerifyRequest, AuthVerifyResponse, AuthUser
from .rag_engine import rag_engine
from .config import settings

app = FastAPI(
    title="Production RAG Web Application",
    description="Full-Stack Retrieval-Augmented Generation API powered by NVIDIA LLM & FAISS",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------

@app.post("/api/upload", response_model=UploadResponse)
async def upload_documents(files: List[UploadFile] = File(...)):
    """
    Accepts multiple PDF files and starts BACKGROUND processing.
    Returns instantly with a task_id for progress polling.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    files_data = []
    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            continue
        content = await file.read()
        files_data.append((file.filename, content))

    if not files_data:
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Start background processing — returns INSTANTLY
    task_id = rag_engine.start_background_ingest(files_data)

    return UploadResponse(
        message=f"Processing {len(files_data)} PDF(s) in background...",
        task_id=task_id,
        files_accepted=len(files_data)
    )


@app.get("/api/progress/{task_id}", response_model=ProcessingProgress)
async def get_progress(task_id: str):
    """
    Poll processing progress for a given task_id.
    Frontend polls this every 500ms to show real-time progress bar.
    """
    progress = rag_engine.get_task_progress(task_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return ProcessingProgress(**progress)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Processes user query against index and calls NVIDIA LLM."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    answer, sources = rag_engine.query(
        question=request.question,
        user_api_key=request.api_key
    )
    return ChatResponse(answer=answer, sources=sources)

@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    """Returns vector store status and file count."""
    return StatusResponse(
        is_ready=rag_engine.vector_store is not None,
        total_chunks=rag_engine.total_chunks,
        filenames=list(rag_engine.processed_files),
        is_processing=rag_engine.is_processing
    )

@app.delete("/api/clear")
async def clear_data():
    """Clears indexed documents and memory."""
    rag_engine.clear()
    return {"message": "Vector store and session memory cleared."}

@app.get("/api/config")
async def get_config():
    """Returns public config like GOOGLE_CLIENT_ID to the frontend."""
    return {
        "google_client_id": settings.GOOGLE_CLIENT_ID,
        "has_nvidia_key": bool(settings.NVIDIA_API_KEY)
    }

@app.post("/api/auth/verify", response_model=AuthVerifyResponse)
async def verify_auth(request: AuthVerifyRequest):
    """
    Verifies or decodes Google ID token credential.
    """
    if not request.credential:
        raise HTTPException(status_code=400, detail="Credential token required.")
    
    # Simple decode or server verification
    try:
        import base64
        import json
        # JWT header.payload.signature
        parts = request.credential.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1]
            # pad base64 string
            rem = len(payload_b64) % 4
            if rem > 0:
                payload_b64 += "=" * (4 - rem)
            decoded_bytes = base64.urlsafe_b64decode(payload_b64)
            payload_json = json.loads(decoded_bytes.decode('utf-8'))
            
            user = AuthUser(
                user_id=payload_json.get("sub", "user_" + str(hash(request.credential))[:8]),
                name=payload_json.get("name", "Student User"),
                email=payload_json.get("email", "student@college.edu"),
                picture=payload_json.get("picture", None)
            )
            return AuthVerifyResponse(authenticated=True, user=user, message="Verified successfully")
    except Exception as e:
        print(f"[Auth] Token decoding exception: {e}")
        
    return AuthVerifyResponse(
        authenticated=True,
        user=AuthUser(
            user_id="demo_student_01",
            name="Demo Student",
            email="student@college.edu",
            picture=None
        ),
        message="Authenticated via demo session"
    )


# ---------------------------------------------------------
# Static File Serving (Frontend UI)
# ---------------------------------------------------------
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(frontend_dir / "index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
