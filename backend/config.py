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
    VISION_MODEL: str = "meta/llama-3.2-11b-vision-instruct"
    # Low variance is important for educational and mathematical answers.
    LLM_TEMPERATURE: float = 0.1
    LLM_TIMEOUT: int = 180
    # Keep answers grounded in the uploaded library.  The optional web fallback
    # requires an additional search provider and otherwise turns usable RAG
    # context into an unhelpful "could not verify online" message.
    ENABLE_WEB_FALLBACK: bool = False

    # ── SPEED-OPTIMIZED CHUNKING ──
    # Massive chunks = far fewer embeddings = dramatically faster
    CHUNK_SIZE: int = 5000
    CHUNK_OVERLAP: int = 500
    TOP_K: int = 4
    DATA_DIR: Path = DATA_DIR

    # ── PROGRESSIVE INDEXING ──
    # How many chunks to embed in the FIRST micro-batch (makes index searchable instantly)
    # Keep the first interactive batch deliberately small so a user can ask
    # questions within seconds; the remaining chunks continue indexing in the
    # background without blocking the conversation.
    FIRST_BATCH_SIZE: int = 8
    # Subsequent background batches
    BACKGROUND_BATCH_SIZE: int = 100
    # Embedding encode batch size (for the model itself)
    EMBED_BATCH_SIZE: int = 512

    def model_post_init(self, __context):
        if not self.NVIDIA_API_KEY or not self.NVIDIA_API_KEY.strip():
            raise ValueError(
                "CRITICAL ERROR: NVIDIA_API_KEY is missing from environment or .env file! "
                "Please configure NVIDIA_API_KEY in your .env file before starting the application."
            )

    class Config:
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
