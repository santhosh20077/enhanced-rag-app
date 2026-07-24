import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

class Settings(BaseSettings):
    NVIDIA_API_KEY: str = ""
    GOOGLE_CLIENT_ID: str = ""
    LLM_MODEL: str = "meta/llama-3.1-8b-instruct"
    LLM_TEMPERATURE: float = 0.2
    LLM_TIMEOUT: int = 180

    # ── SPEED-OPTIMIZED CHUNKING ──
    # Massive chunks = far fewer embeddings = dramatically faster
    CHUNK_SIZE: int = 5000
    CHUNK_OVERLAP: int = 500
    TOP_K: int = 4
    DATA_DIR: Path = DATA_DIR

    # ── PROGRESSIVE INDEXING ──
    # How many chunks to embed in the FIRST micro-batch (makes index searchable instantly)
    FIRST_BATCH_SIZE: int = 30
    # Subsequent background batches
    BACKGROUND_BATCH_SIZE: int = 100
    # Embedding encode batch size (for the model itself)
    EMBED_BATCH_SIZE: int = 512

    class Config:
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
