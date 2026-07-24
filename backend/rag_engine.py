import os
import io
import time
import uuid
import threading
import numpy as np
from typing import List, Tuple, Dict, Any, Optional
from pathlib import Path

import fitz  # PyMuPDF

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from .config import settings
from .models import SourceDocument


class ProcessingTask:
    """Tracks a background file processing task with progressive indexing."""
    def __init__(self, task_id: str, total_files: int):
        self.task_id = task_id
        self.status = "parsing"
        self.progress = 0.0
        self.stage_label = "Extracting text from PDF pages..."
        self.files_total = total_files
        self.pages_extracted = 0
        self.chunks_created = 0
        self.chunks_indexed = 0
        self.start_time = time.time()
        self.error: Optional[str] = None
        self.is_searchable = False  # True once first batch is indexed

    @property
    def elapsed(self) -> float:
        return round(time.time() - self.start_time, 1)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "progress": round(self.progress, 3),
            "stage_label": self.stage_label,
            "files_total": self.files_total,
            "pages_extracted": self.pages_extracted,
            "chunks_created": self.chunks_created,
            "elapsed_seconds": self.elapsed,
            "error": self.error,
        }


class RAGEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
            encode_kwargs={
                "normalize_embeddings": True,
                "batch_size": settings.EMBED_BATCH_SIZE,
            }
        )
        self.vector_store: FAISS = None
        self.index_path = settings.DATA_DIR / "faiss_index"
        self.processed_files: set = set()
        self.total_chunks: int = 0

        # Background processing state & conversation memory
        self._processing_tasks: Dict[str, ProcessingTask] = {}
        self._is_processing = False
        self.chat_history: Dict[str, list] = {}

        self._load_vector_store()

    def _load_vector_store(self):
        """Loads persistent vector store if exists on disk."""
        if (self.index_path / "index.faiss").exists():
            try:
                self.vector_store = FAISS.load_local(
                    str(self.index_path),
                    self.embeddings,
                    allow_dangerous_deserialization=True
                )
                self.total_chunks = len(self.vector_store.docstore._dict) if hasattr(self.vector_store, 'docstore') else 0
                print(f"[RAGEngine] Loaded persistent FAISS index with {self.total_chunks} chunks.")
            except Exception as e:
                print(f"[RAGEngine] Failed to load persistent index: {e}")
                self.vector_store = None

    def _save_vector_store(self):
        """Saves current vector store to disk."""
        if self.vector_store:
            self.vector_store.save_local(str(self.index_path))

    @property
    def is_processing(self) -> bool:
        return self._is_processing

    def get_task_progress(self, task_id: str) -> Optional[dict]:
        task = self._processing_tasks.get(task_id)
        if task:
            return task.to_dict()
        return None

    def _extract_text_pymupdf(self, content: bytes, filename: str) -> List[Document]:
        """Extract text from PDF using PyMuPDF (fitz)."""
        documents = []
        try:
            doc = fitz.open(stream=content, filetype="pdf")
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                text = page.get_text("text")
                if text and text.strip():
                    documents.append(Document(
                        page_content=text,
                        metadata={
                            "source_filename": filename,
                            "page_number": page_idx + 1
                        }
                    ))
            doc.close()
        except Exception as e:
            print(f"[RAGEngine] Error extracting {filename} with PyMuPDF: {e}")
        return documents

    def start_background_ingest(self, files_data: List[Tuple[str, bytes]]) -> str:
        """Starts background ingestion with progressive indexing. Returns instantly."""
        task_id = str(uuid.uuid4())[:8]
        task = ProcessingTask(task_id, len(files_data))
        self._processing_tasks[task_id] = task
        self._is_processing = True

        thread = threading.Thread(
            target=self._progressive_ingest_worker,
            args=(task, files_data),
            daemon=True
        )
        thread.start()
        return task_id

    def _progressive_ingest_worker(self, task: ProcessingTask, files_data: List[Tuple[str, bytes]]):
        """PROGRESSIVE INDEXING WORKER"""
        try:
            t0 = time.time()

            # PHASE 1: PDF PARSING
            task.status = "parsing"
            task.stage_label = "Extracting text with PyMuPDF..."
            task.progress = 0.0

            all_documents: List[Document] = []
            for filename, content in files_data:
                docs = self._extract_text_pymupdf(content, filename)
                all_documents.extend(docs)
                self.processed_files.add(filename)
                task.pages_extracted += len(docs)

            parse_time = time.time() - t0
            task.progress = 0.15
            print(f"[RAGEngine] PyMuPDF extracted {task.pages_extracted} pages in {parse_time:.2f}s")

            if not all_documents:
                task.status = "complete"
                task.progress = 1.0
                task.stage_label = "No extractable text found in uploaded files."
                self._is_processing = False
                return

            # PHASE 2: CHUNKING
            task.status = "chunking"
            task.stage_label = f"Splitting {len(all_documents)} pages into chunks..."
            task.progress = 0.20

            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=settings.CHUNK_SIZE,
                chunk_overlap=settings.CHUNK_OVERLAP,
                separators=["\n\n", "\n", ". ", " ", ""]
            )
            all_chunks = text_splitter.split_documents(all_documents)
            task.chunks_created = len(all_chunks)
            task.progress = 0.25

            chunk_time = time.time() - t0
            print(f"[RAGEngine] Created {len(all_chunks)} chunks in {chunk_time:.2f}s total")

            # PHASE 3: FIRST BATCH — INSTANT AVAILABILITY
            first_batch_size = min(settings.FIRST_BATCH_SIZE, len(all_chunks))
            first_batch = all_chunks[:first_batch_size]
            remaining_chunks = all_chunks[first_batch_size:]

            task.status = "embedding"
            task.stage_label = f"Quick-indexing first {first_batch_size} chunks for instant search..."
            task.progress = 0.30

            with self._lock:
                if self.vector_store is None:
                    self.vector_store = FAISS.from_documents(first_batch, self.embeddings)
                else:
                    self.vector_store.add_documents(first_batch)

            task.chunks_indexed = first_batch_size
            task.is_searchable = True
            first_batch_time = time.time() - t0
            print(f"[RAGEngine] FIRST BATCH INDEXED in {first_batch_time:.2f}s -- SEARCHABLE NOW!")

            if not remaining_chunks:
                with self._lock:
                    self._save_vector_store()
                    self.total_chunks = len(self.vector_store.docstore._dict)
                task.status = "complete"
                task.progress = 1.0
                task.stage_label = f"Done! {task.pages_extracted} pages -> {task.chunks_created} chunks in {task.elapsed}s"
                self._is_processing = False
                return

            # PHASE 4: BACKGROUND BATCHES
            task.status = "background"
            total_remaining = len(remaining_chunks)
            batch_size = settings.BACKGROUND_BATCH_SIZE
            indexed_so_far = first_batch_size

            for i in range(0, total_remaining, batch_size):
                batch = remaining_chunks[i:i + batch_size]
                task.stage_label = f"Background indexing... {indexed_so_far}/{task.chunks_created} chunks (you can chat now!)"

                with self._lock:
                    self.vector_store.add_documents(batch)

                indexed_so_far += len(batch)
                task.chunks_indexed = indexed_so_far
                task.progress = 0.40 + 0.55 * (indexed_so_far / task.chunks_created)

            # SAVE & FINALIZE
            task.status = "saving"
            task.stage_label = "Saving index to disk..."
            task.progress = 0.97

            with self._lock:
                self._save_vector_store()
                self.total_chunks = len(self.vector_store.docstore._dict)

            task.status = "complete"
            task.progress = 1.0
            task.stage_label = f"Done! {task.pages_extracted} pages -> {task.chunks_created} chunks in {task.elapsed}s"
            self._is_processing = False
            print(f"[RAGEngine] FULL INGEST COMPLETE: {task.pages_extracted} pages, {task.chunks_created} chunks, {task.elapsed}s")

        except Exception as e:
            task.status = "error"
            task.error = str(e)
            task.stage_label = f"Error during ingestion: {e}"
            self._is_processing = False
            print(f"[RAGEngine] Ingestion error: {e}")

    def clear(self):
        """Clears vector store and memory."""
        with self._lock:
            self.vector_store = None
            self.processed_files.clear()
            self.total_chunks = 0
            self.chat_history.clear()
            if (self.index_path / "index.faiss").exists():
                try:
                    os.remove(self.index_path / "index.faiss")
                    os.remove(self.index_path / "index.pkl")
                except Exception as e:
                    print(f"[RAGEngine] Error clearing index files: {e}")

    def query(self, question: str, session_id: str = "default", user_api_key: str = None) -> Tuple[str, List[SourceDocument]]:
        """Queries top-k retrieved context and invokes ChatNVIDIA with multi-turn conversation memory."""
        if not self.vector_store:
            return "No documents have been uploaded yet. Please upload PDF files first.", []

        history = self.chat_history.get(session_id, [])
        recent_history = history[-5:]

        api_key = user_api_key or settings.NVIDIA_API_KEY
        if not api_key:
            return "NVIDIA API Key is missing. Please provide your API key in the sidebar.", []

        search_query = question
        if recent_history:
            try:
                llm_rephrase = ChatNVIDIA(
                    model=settings.LLM_MODEL,
                    nvidia_api_key=api_key,
                    temperature=0.1,
                    timeout=settings.LLM_TIMEOUT
                )
                formatted_history = "\n".join([f"Human: {u_msg}\nAI: {a_msg}" for u_msg, a_msg in recent_history])
                rephrase_prompt = ChatPromptTemplate.from_template(
                    "Given the conversation history and a new user message, rewrite the new message into a single standalone question that includes all necessary context from the history. Do not answer the question. Only output the rewritten question, nothing else.\n\nCONVERSATION HISTORY:\n{history}\n\nNEW USER MESSAGE:\n{question}\n\nSTANDALONE QUESTION:"
                )
                rephrase_chain = rephrase_prompt | llm_rephrase | StrOutputParser()
                rewritten = rephrase_chain.invoke({"history": formatted_history, "question": question}).strip()
                if rewritten:
                    search_query = rewritten
                    print(f"[RAGEngine] Standalone Search Query: '{search_query}'")
            except Exception as e:
                print(f"[RAGEngine] Rephrase query failed, using fallback string concat: {e}")
                last_user_q = recent_history[-1][0]
                search_query = f"{last_user_q} {question}"

        retriever = self.vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": settings.TOP_K}
        )
        retrieved_docs: List[Document] = retriever.invoke(search_query)

        context_parts = []
        sources: List[SourceDocument] = []

        for doc in retrieved_docs:
            page_num = doc.metadata.get("page_number", 1)
            fname = doc.metadata.get("source_filename", "Unknown")
            context_parts.append(f"[File: {fname} | Page {page_num}]\n{doc.page_content}")
            sources.append(
                SourceDocument(
                    page_number=page_num,
                    filename=fname,
                    snippet=doc.page_content[:300] + "..." if len(doc.page_content) > 300 else doc.page_content
                )
            )

        context_str = "\n\n---\n\n".join(context_parts)

        try:
            llm = ChatNVIDIA(
                model=settings.LLM_MODEL,
                nvidia_api_key=api_key,
                temperature=settings.LLM_TEMPERATURE,
                timeout=settings.LLM_TIMEOUT
            )

            prompt_messages = [
                ("system", f"""You are an expert AI Academic Tutor designed to provide clear, easy-to-read, and stress-free answers for students.

RESPONSE FORMATTING & STRUCTURE RULES:
1. **Direct Summary First**: Start with a concise 1-2 sentence direct summary answering the question clearly.
2. **Use Bullet Points & Lists**: Break down explanations into scannable bullet points or numbered steps. Avoid long, overwhelming paragraphs or walls of text.
3. **Use Section Headings**: Group distinct parts of your answer under bold section headings (e.g., ### Key Concepts, ### Step-by-Step Breakdown, ### Summary).
4. **Highlight Key Terms**: Use **bold text** for essential terms, formulas, and definitions so students can grasp key ideas at a glance.
5. **Page Citations**: Always reference page numbers using [Page X] tags when stating facts from the documents.
6. **Multi-Turn Continuity**: Remember prior context from our conversation history to answer follow-up questions naturally.
7. **Clarity & Tone**: Use clear, reassuring, and precise language. If the answer is not in the context, explicitly say: "I could not find this information in the uploaded documents."

Context:
{context_str}""")
            ]

            for u_msg, a_msg in recent_history:
                prompt_messages.append(("human", u_msg))
                prompt_messages.append(("ai", a_msg))

            prompt_messages.append(("human", question))

            prompt = ChatPromptTemplate.from_messages(prompt_messages)
            chain = prompt | llm | StrOutputParser()
            answer = chain.invoke({})

            if session_id not in self.chat_history:
                self.chat_history[session_id] = []
            self.chat_history[session_id].append((question, answer))

            return answer, sources

        except Exception as e:
            err_msg = str(e)
            if "401" in err_msg or "unauthorized" in err_msg.lower():
                return "❌ Error: Invalid NVIDIA API Key. Please check your credentials.", []
            elif "429" in err_msg or "rate limit" in err_msg.lower():
                return "⏳ Error: NVIDIA API Rate limit reached. Please try again in a few seconds.", []
            return f"❌ Error communicating with NVIDIA AI API: {err_msg}", []


# Global singleton engine
rag_engine = RAGEngine()