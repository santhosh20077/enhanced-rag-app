# Production-Ready Full-Stack RAG Web Application

A full-stack Retrieval-Augmented Generation (RAG) web application powered by **FastAPI**, **NVIDIA AI Endpoints** (`meta/llama-3.1-8b-instruct`), **FAISS Vector Store**, **Local HuggingFace Embeddings**, and a sleek **Dark Glassmorphism Chat Frontend**.

---

## 🏗️ Architecture

```
rag-app/
├── backend/
│   ├── main.py              # FastAPI app initialization, CORS, static routes
│   ├── config.py            # App & API settings (pydantic-settings)
│   ├── rag_engine.py        # PDF extraction, page metadata, FAISS & LCEL RAG chain
│   ├── models.py            # Pydantic schemas for requests/responses
│   └── requirements.txt     # Python backend dependencies
├── frontend/                # Single-Page Web UI (Dark Glassmorphism)
│   ├── index.html           # SPA HTML layout
│   ├── app.js               # Async API client & UI rendering
│   └── styles.css           # Modern dark mode design system
├── data/                    # Local persistent FAISS vector indices
├── .env.example             # Template for environment configuration
└── README.md
```

---

## ⚡ Core Features

1. **Document Ingestion & Metadata Tracking**:
   - Page-by-page PDF extraction using `PyPDF2`.
   - Preserves `source_filename` and `page_number` for every chunk.
   - Text chunking via `RecursiveCharacterTextSplitter` (1500 chars, 200 overlap).
   - Local embeddings generated with `sentence-transformers/all-MiniLM-L6-v2`.
   - Vectors saved persistently to disk in `data/faiss_index`.

2. **NVIDIA LLM & Citation Retrieval**:
   - Queries `meta/llama-3.1-8b-instruct` via `langchain-nvidia-ai-endpoints`.
   - Formats context with explicit `[File: X | Page Y]` page tags.
   - Returns structured answers along with expandable **Source Page Citations** showing file name, page number, and relevant document snippets.

3. **Production Web Interface**:
   - Sidebar for NVIDIA API key management and drag-and-drop PDF uploads.
   - Real-time status indicators (Total Chunks, Ready status, File list).
   - ChatGPT-style responsive dark mode conversation UI.
   - "Clear Index & Chat" functionality.

---

## 🚀 Quick Start Guide

### 1. Install Dependencies

Navigate to the project directory and install the backend requirements:

```bash
cd "rag-app/backend"
pip install -r requirements.txt
```

### 2. Configure API Key (Optional)

Create a `.env` file from `.env.example` in the `rag-app` root directory:

```bash
NVIDIA_API_KEY=nvapi-your-key-here
```
*(Note: You can also enter your API key directly in the sidebar of the Web UI at runtime)*

### 3. Run the Server

From the `rag-app` directory, start the FastAPI server:

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Open in Browser

Open your browser and visit:
👉 **[http://localhost:8000](http://localhost:8000)**
