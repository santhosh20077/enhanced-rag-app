import os
import io
import time
import uuid
import json
import threading
import numpy as np
from typing import List, Tuple, Dict, Any, Optional, Generator
from pathlib import Path

import fitz  # PyMuPDF

import base64
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_community.tools import DuckDuckGoSearchResults
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
import io
from PIL import Image
import pillow_heif
import filetype
import re

# Register HEIF opener
pillow_heif.register_heif_opener()

# Lazy-load EasyOCR to avoid slow import at startup
_ocr_reader = None
def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        print('[RAGEngine] EasyOCR reader initialized.')
    return _ocr_reader

# Non-answer detection patterns
_NON_ANSWER_PATTERNS = [
    r"i couldn'?t find",
    r"i could not find",
    r"i don'?t know",
    r"i do not know",
    r"no relevant information",
    r"not found in",
    r"outside the scope",
    r"no text .* image",
    r"couldn'?t (?:extract|read|identify|find any text)",
    r"unable to (?:extract|read|identify|find)",
    r"i'?m having trouble reading",
    r"no answer found",
    r"does not (?:contain|include|mention|cover)",
    r"not (?:contain|include|mention|cover)",
    r"cannot (?:determine|identify|extract|read)",
    r"may be outside",
    r"i apologize",
    r"unfortunately",
]
_NON_ANSWER_RE = re.compile('|'.join(_NON_ANSWER_PATTERNS), re.IGNORECASE)

def _is_non_answer(text: str) -> bool:
    """Detect if an LLM response is a non-answer / failure message."""
    stripped = text.strip()
    if len(stripped) < 25:
        return True
    if _NON_ANSWER_RE.search(stripped):
        return True
    return False

from .config import settings
from .models import SourceDocument, FileDetail, InlineAttachment


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
            model_name="all-MiniLM-L6-v2"
        )
        self.vector_store: FAISS = None
        self.index_path = settings.DATA_DIR / "faiss_index"
        self.processed_files: set = set()
        self.total_chunks: int = 0
        self.metadata_path = self.index_path / "metadata.json"

        # Background processing state & conversation memory
        self._processing_tasks: Dict[str, ProcessingTask] = {}
        self._is_processing = False
        self.chat_history: Dict[str, list] = {}
        # Stores extracted image content per session for follow-up questions
        self.image_context: Dict[str, str] = {}

        # Per-file metadata tracking
        self.file_details: Dict[str, FileDetail] = {}
        self.total_indexing_time: float = 0.0
        self.avg_chunk_size: float = 0.0

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
                if self.metadata_path.exists():
                    saved = json.loads(self.metadata_path.read_text(encoding="utf-8"))
                    self.processed_files = set(saved.get("processed_files", []))
                    self.file_details = {
                        name: FileDetail(**detail)
                        for name, detail in saved.get("file_details", {}).items()
                    }
                    self.total_indexing_time = saved.get("total_indexing_time", 0.0)
                    self.avg_chunk_size = saved.get("avg_chunk_size", 0.0)
                else:
                    # Recover basic file identity from document metadata for indexes
                    # created before metadata persistence was added.
                    docs = list(self.vector_store.docstore._dict.values())
                    self.processed_files = {
                        doc.metadata.get("source_filename") for doc in docs
                        if doc.metadata.get("source_filename")
                    }
                    for name in self.processed_files:
                        file_docs = [d for d in docs if d.metadata.get("source_filename") == name]
                        self.file_details[name] = FileDetail(
                            filename=name,
                            page_count=len({d.metadata.get("page_number") for d in file_docs}),
                            chunk_count=len(file_docs),
                        )
                self.metadata_path.write_text(json.dumps({
                    "processed_files": sorted(self.processed_files),
                    "file_details": {name: detail.model_dump() for name, detail in self.file_details.items()},
                    "total_indexing_time": self.total_indexing_time,
                    "avg_chunk_size": self.avg_chunk_size,
                }), encoding="utf-8")
                print(f"[RAGEngine] Loaded persistent FAISS index with {self.total_chunks} chunks.")
            except Exception as e:
                print(f"[RAGEngine] Failed to load persistent index: {e}")
                self.vector_store = None

    def _save_vector_store(self):
        """Saves current vector store to disk."""
        if self.vector_store:
            self.vector_store.save_local(str(self.index_path))
        self.index_path.mkdir(parents=True, exist_ok=True)
        self.metadata_path.write_text(json.dumps({
            "processed_files": sorted(self.processed_files),
            "file_details": {name: detail.model_dump() for name, detail in self.file_details.items()},
            "total_indexing_time": self.total_indexing_time,
            "avg_chunk_size": self.avg_chunk_size,
        }), encoding="utf-8")

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

                # Track per-file metadata
                page_count = len(docs)
                self.file_details[filename] = FileDetail(
                    filename=filename,
                    size_bytes=len(content),
                    page_count=page_count,
                    chunk_count=0,
                    upload_time=time.time()
                )

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

            # Update per-file chunk counts and compute avg chunk size
            file_chunk_counts: Dict[str, int] = {}
            total_chunk_chars = 0
            for chunk in all_chunks:
                fn = chunk.metadata.get("source_filename", "Unknown")
                file_chunk_counts[fn] = file_chunk_counts.get(fn, 0) + 1
                total_chunk_chars += len(chunk.page_content)

            for fn, count in file_chunk_counts.items():
                if fn in self.file_details:
                    self.file_details[fn].chunk_count = count

            if len(all_chunks) > 0:
                self.avg_chunk_size = round(total_chunk_chars / len(all_chunks), 1)

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
                self.total_indexing_time = round(time.time() - t0, 2)
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
            self.total_indexing_time = round(time.time() - t0, 2)
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
            self.file_details.clear()
            self.total_indexing_time = 0.0
            self.avg_chunk_size = 0.0
            if (self.index_path / "index.faiss").exists():
                try:
                    os.remove(self.index_path / "index.faiss")
                    os.remove(self.index_path / "index.pkl")
                    if self.metadata_path.exists():
                        os.remove(self.metadata_path)
                except Exception as e:
                    print(f"[RAGEngine] Error clearing index files: {e}")

    def remove_file(self, filename: str) -> bool:
        """Remove one uploaded file and rebuild the persistent index."""
        if filename not in self.processed_files:
            return False

        with self._lock:
            if not self.vector_store or not hasattr(self.vector_store, "docstore"):
                return False

            remaining_docs = [
                doc for doc in self.vector_store.docstore._dict.values()
                if doc.metadata.get("source_filename") != filename
            ]
            self.processed_files.discard(filename)
            self.file_details.pop(filename, None)

            if remaining_docs:
                self.vector_store = FAISS.from_documents(remaining_docs, self.embeddings)
                self.total_chunks = len(remaining_docs)
                self.avg_chunk_size = sum(len(doc.page_content) for doc in remaining_docs) / len(remaining_docs)
                self._save_vector_store()
            else:
                self.vector_store = None
                self.total_chunks = 0
                self.avg_chunk_size = 0.0
                for index_file in (self.index_path / "index.faiss", self.index_path / "index.pkl"):
                    if index_file.exists():
                        index_file.unlink()

        return True

    # ----------------------------------------------------------
    # RETRIEVAL HELPER (shared by query and query_stream)
    # ----------------------------------------------------------
    def _retrieve_context(self, question: str, session_id: str = "default"):
        """Retrieves context, sources, and confidence score. Returns (context_str, sources, confidence, search_query)."""
        if not self.vector_store:
            return None, [], 0.0, question

        history = self.chat_history.get(session_id, [])
        recent_history = history[-5:]

        api_key = settings.NVIDIA_API_KEY
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
                rephrase_msg = HumanMessage(content=f"Given the conversation history and a new user message, rewrite the new message into a single standalone question that includes all necessary context from the history. Do not answer the question. Only output the rewritten question, nothing else.\n\nCONVERSATION HISTORY:\n{formatted_history}\n\nNEW USER MESSAGE:\n{question}\n\nSTANDALONE QUESTION:")
                rephrase_chain = llm_rephrase | StrOutputParser()
                rewritten = rephrase_chain.invoke([rephrase_msg]).strip()
                if rewritten:
                    search_query = rewritten
                    print(f"[RAGEngine] Standalone Search Query: '{search_query}'")
            except Exception as e:
                print(f"[RAGEngine] Rephrase query failed, using fallback string concat: {e}")
                last_user_q = recent_history[-1][0]
                search_query = f"{last_user_q} {question}"

        # Use similarity_search_with_score for confidence calculation
        with self._lock:
            try:
                docs_with_scores = self.vector_store.similarity_search_with_score(search_query, k=settings.TOP_K)
            except Exception:
                retriever = self.vector_store.as_retriever(search_type="similarity", search_kwargs={"k": settings.TOP_K})
                retrieved_docs = retriever.invoke(search_query)
                docs_with_scores = [(doc, 0.5) for doc in retrieved_docs]

        context_parts = []
        sources: List[SourceDocument] = []
        scores = []

        for doc, score in docs_with_scores:
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
            # FAISS L2 distance: lower = better. Convert to 0-1 confidence.
            scores.append(float(score))

        # Convert L2 distances to confidence: conf = max(0, 1 - avg_dist / 2)
        if scores:
            avg_dist = sum(scores) / len(scores)
            confidence = max(0.0, min(1.0, 1.0 - avg_dist / 2.0))
        else:
            confidence = 0.0

        context_str = "\n\n---\n\n".join(context_parts)
        return context_str, sources, round(confidence, 3), search_query

    def _build_system_prompt(self, context_str: str, eli5_mode: bool = False) -> str:
        """Builds the system prompt with optional ELI5 mode."""
        eli5_instruction = ""
        if eli5_mode:
            eli5_instruction = """
SPECIAL MODE: EXPLAIN LIKE I'M 5 (ELI5)
- Use extremely simple language that a young child could understand.
- Replace technical jargon with everyday words and fun analogies.
- Use short sentences and simple comparisons.
- Add emoji where helpful to keep it fun and engaging.
- Keep explanations brief and focused on the core concept.

"""

        return f"""You are the document-grounded retrieval assistant for this workspace. Provide clear, easy-to-read, and stress-free answers for students.
Do not describe yourself as an LLM, language model, chatbot, or AI. Do not discuss your internal model or implementation. Answer the user's question directly using the retrieved documents and attached images. Never invent facts when the sources do not support them.
{eli5_instruction}
RESPONSE FORMATTING & STRUCTURE RULES:
1. **Direct Summary First**: Start with a concise 1-2 sentence direct summary answering the question clearly.
2. **Use Bullet Points & Lists**: Break down explanations into scannable bullet points or numbered steps. Avoid long, overwhelming paragraphs or walls of text.
3. **Use Section Headings**: Group distinct parts of your answer under bold section headings (e.g., ### Key Concepts, ### Step-by-Step Breakdown, ### Summary).
4. **Highlight Key Terms**: Use **bold text** for essential terms, formulas, and definitions so students can grasp key ideas at a glance.
5. **Page Citations**: Always reference page numbers using [Page X] tags when stating facts from the documents.
6. **Multi-Turn Continuity**: Remember prior context from our conversation history to answer follow-up questions naturally.
7. **Clarity & Tone**: Use clear, reassuring, and precise language. If the answer is not in the context, explicitly say: "I could not find this information in the uploaded documents."
8. **Readable Math & Symbols**: Prefer proper mathematical and logical notation over code-style text. Write formulas in LaTeX-style notation when possible, using subscripts, superscripts, fractions, inequalities, set symbols, arrows, quantifiers, and Greek letters. For example write "a_{{n+2}} - 2a_{{n+1}} + a_n = 2^n, n \\ge 0" instead of "a_n+2 - 2a_n+1 + a_n = 2n". Briefly explain uncommon symbols the first time they appear.
9. **Strict Mathematics Accuracy Protocol**: When the user asks mathematics, accuracy matters more than speed or fluency. Follow this process strictly:
   - **Step 1 — Understand before solving**: Restate the problem in your own words, including what is given and asked. Identify the exact category/technique required (for example, non-homogeneous linear recurrence or substitution). Do not blindly apply a retrieved template; check its assumptions and adapt or state the mismatch.
   - **Step 2 — Solve step by step**: Show every logical algebraic step. Keep separate components separate, such as homogeneous and particular solutions. Never substitute a function of n into an equation intended to determine a constant.
   - **Step 3 — Sanity-check**: Check intermediate results for correct signs, roots, multiplicity, domains, units, probability range, or expected behavior. If something fails, stop and re-derive it.
   - **Step 4 — Final answer**: Clearly separate the final answer from the working.
   - **Step 5 — Mandatory independent verification**: Verify using a different method. For equations or recurrences, substitute the result into the original problem and test at least 2–3 valid values, including boundary values such as n=0 or n=1 when applicable. For derivatives/integrals, differentiate or numerically compare. For probability/combinatorics, test a smaller or edge case. If verification fails, fix the derivation and verify again. Never present an unverified answer.
   - **Step 6 — Report**: End with the method used, the final answer, and one line stating exactly what independent verification was performed and that it passed. If verification cannot be completed, say so explicitly and do not claim the answer is confirmed.
   Treat the problem statement as authoritative, do not guess missing values, and mark unclear image symbols for confirmation instead of silently choosing an interpretation.
10. **Answer Reliability**: Keep the derivation separate from the final result. Show enough intermediate work for a student or teacher to audit every sign, exponent, index, denominator, and boundary condition. For non-mathematical questions, distinguish retrieved facts from explanations and say when the documents do not contain enough evidence.
11. **No Repetition**: Never repeat the same equation, sentence, or derivation line. After writing a formula once, continue to the next logical step. Keep the answer focused and stop when the requested verification is complete.

Context:
{context_str}"""

    def _generate_follow_up_suggestions(self, question: str, answer: str) -> List[str]:
        """Generate 2-3 follow-up question suggestions based on the Q&A."""
        try:
            api_key = settings.NVIDIA_API_KEY
            llm = ChatNVIDIA(
                model=settings.LLM_MODEL,
                nvidia_api_key=api_key,
                temperature=0.7,
                timeout=30
            )
            msg = HumanMessage(content=f"""Based on this Q&A exchange, suggest exactly 3 short follow-up questions the student might want to ask next. Output ONLY the 3 questions, one per line, no numbering, no bullets, no extra text.

Question: {question}
Answer (first 500 chars): {answer[:500]}

Follow-up questions:""")
            chain = llm | StrOutputParser()
            result = chain.invoke([msg]).strip()
            suggestions = [line.strip().lstrip('0123456789.-) ') for line in result.split('\n') if line.strip() and len(line.strip()) > 5]
            return suggestions[:3]
        except Exception as e:
            print(f"[RAGEngine] Follow-up suggestion generation failed: {e}")
            return []
    # ----------------------------------------------------------
    def _perform_web_search(self, query: str) -> Tuple[str, List[SourceDocument]]:
        """Performs a background web search using DuckDuckGo."""
        print(f"[RAGEngine] Performing web search for: '{query}'")
        try:
            wrapper = DuckDuckGoSearchAPIWrapper(max_results=3)
            search = DuckDuckGoSearchResults(api_wrapper=wrapper)
            # DuckDuckGoSearchAPIWrapper returns a list of dicts when using results()
            results = wrapper.results(query, max_results=3)
            
            web_context = ""
            sources = []
            
            for res in results:
                title = res.get('title', 'Web Page')
                link = res.get('link', '')
                snippet = res.get('snippet', '')
                
                web_context += f"Source URL: {link}\nTitle: {title}\nContent: {snippet}\n\n"
                sources.append(SourceDocument(
                    filename=link,
                    content=snippet,
                    page_num=0,
                    metadata={"url": link, "title": title, "source_type": "web"}
                ))
            
            if not web_context.strip():
                return "", []
                
            print(f"[RAGEngine] Web search returned {len(sources)} results.")
            return web_context, sources
        except Exception as e:
            print(f"[RAGEngine] Web search failed: {e}")
            return "", []

    # ----------------------------------------------------------
    def _process_attachments(self, attachments: List[InlineAttachment]) -> dict:
        """Processes inline attachments: extracts text from PDFs, runs OCR on images,
        and prepares multimodal payloads for the vision model.
        
        Returns a dict with:
          - 'text': combined text context from all attachments (OCR + PDF text)
          - 'image_payloads': list of base64 JPEG data URIs for vision model
          - 'has_images': whether any images were successfully processed
          - 'ocr_text': raw OCR-extracted text from images
        """
        result = {'text': '', 'image_payloads': [], 'has_images': False, 'ocr_text': ''}
        if not attachments:
            return result
            
        attachment_text = []
        ocr_texts = []
        
        for att in attachments:
            if att.filename.lower().endswith(".pdf"):
                try:
                    pdf_bytes = base64.b64decode(att.data)
                    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    extracted = ""
                    for page in doc:
                        extracted += page.get_text("text") + "\n"
                    doc.close()
                    if extracted.strip():
                        attachment_text.append(f"[Attachment: {att.filename}]\n{extracted.strip()}")
                except Exception as e:
                    print(f"[RAGEngine] Error extracting inline PDF {att.filename}: {e}")
            elif att.mime_type.startswith("image/") or att.filename.lower().endswith(('.heic', '.heif', '.tiff', '.tif', '.bmp', '.svg', '.avif', '.ico')):
                try:
                    img_bytes = base64.b64decode(att.data)
                    print(f"[RAGEngine] Image payload size for '{att.filename}': {len(img_bytes)} bytes")
                    
                    if len(img_bytes) == 0:
                        attachment_text.append(f"[Image '{att.filename}' was empty or corrupted - please re-upload]")
                        continue
                    
                    # Validate magic bytes
                    kind = filetype.guess(img_bytes)
                    if kind is None or not (kind.mime.startswith('image/') or kind.extension in ['heic', 'heif']):
                        attachment_text.append("[Couldn't process this image format - try PNG, JPG, or HEIC]")
                        continue
                        
                    # SVGs are XML text, can't be rasterized here
                    if kind.extension == 'svg' or att.filename.lower().endswith('.svg'):
                        attachment_text.append("[Couldn't process this image format - try PNG, JPG, or HEIC]")
                        continue

                    # Open and convert to high-quality JPEG for both OCR and vision model
                    img = Image.open(io.BytesIO(img_bytes))
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    
                    # Resize very large images to max 2048px on longest side to save bandwidth
                    # but keep enough resolution for OCR
                    max_dim = 2048
                    if max(img.size) > max_dim:
                        ratio = max_dim / max(img.size)
                        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                        img = img.resize(new_size, Image.LANCZOS)
                        print(f"[RAGEngine] Resized image to {new_size}")
                    
                    output = io.BytesIO()
                    img.save(output, format="JPEG", quality=90)
                    jpeg_bytes = output.getvalue()
                    standard_jpeg_b64 = base64.b64encode(jpeg_bytes).decode('utf-8')
                    print(f"[RAGEngine] Converted JPEG size: {len(jpeg_bytes)} bytes")
                    
                    # Store the standardized base64 back into the attachment
                    att.data = standard_jpeg_b64
                    att.mime_type = "image/jpeg"
                    
                    # Add to vision model payloads
                    data_uri = f"data:image/jpeg;base64,{standard_jpeg_b64}"
                    result['image_payloads'].append(data_uri)
                    result['has_images'] = True
                    
                    # --- Run EasyOCR for text extraction ---
                    try:
                        reader = _get_ocr_reader()
                        # Convert PIL image to numpy array for easyocr
                        img_np = np.array(img)
                        ocr_results = reader.readtext(img_np, detail=0, paragraph=True)
                        ocr_extracted = "\n".join(ocr_results).strip()
                        
                        if ocr_extracted:
                            print(f"[RAGEngine] OCR extracted {len(ocr_extracted)} chars from '{att.filename}'")
                            ocr_texts.append(ocr_extracted)
                            attachment_text.append(
                                f"[OCR Text from image '{att.filename}']:\n{ocr_extracted}"
                            )
                        else:
                            print(f"[RAGEngine] OCR found no text in '{att.filename}'")
                    except Exception as ocr_err:
                        print(f"[RAGEngine] OCR failed for '{att.filename}': {ocr_err}")
                    
                except Exception as e:
                    print(f"[RAGEngine] Error converting image {att.filename}: {e}")
                    attachment_text.append("[Couldn't process this image format - try PNG, JPG, or HEIC]")
        if attachment_text:
            result['text'] = "\n\n--- INLINE ATTACHMENTS ---\n\n" + "\n\n".join(attachment_text)
        if ocr_texts:
            result['ocr_text'] = "\n\n".join(ocr_texts)
        return result

    # ----------------------------------------------------------
    # ORIGINAL QUERY (kept for backward compat)
    # ----------------------------------------------------------
    def query(self, question: str, session_id: str = "default", eli5_mode: bool = False, attachments: List[InlineAttachment] = None) -> Tuple[str, List[SourceDocument], float, List[str]]:
        """Queries top-k retrieved context and invokes ChatNVIDIA with multi-turn conversation memory.
        Returns (answer, sources, confidence_score, follow_up_suggestions)."""
        context_str, sources, confidence, search_query = self._retrieve_context(question, session_id)
        
        # Process inline attachments
        att_data = self._process_attachments(attachments or [])
        att_context = att_data['text']
        
        if context_str is None and not att_context and not att_data['has_images']:
            return "No documents have been uploaded yet. Please upload PDF files first.", [], 0.0, []

        api_key = settings.NVIDIA_API_KEY
        if not api_key:
            return "NVIDIA API Key is missing on the server. Please configure NVIDIA_API_KEY in the backend environment.", [], 0.0, []

        history = self.chat_history.get(session_id, [])
        recent_history = history[-5:]

        try:
            # Switch to vision model when images are present
            model_name = settings.VISION_MODEL if att_data['has_images'] else settings.LLM_MODEL
            print(f"[RAGEngine] Using model: {model_name}")
            
            llm = ChatNVIDIA(
                model=model_name,
                nvidia_api_key=api_key,
                temperature=settings.LLM_TEMPERATURE,
                timeout=settings.LLM_TIMEOUT
            )

            system_prompt = self._build_system_prompt(context_str if context_str else "", eli5_mode)
            
            # Add explicit image reading instructions when images are present
            if att_data['has_images']:
                system_prompt += (
                    "\n\nIMPORTANT IMAGE INSTRUCTIONS: The user has attached an image. "
                    "Carefully read ALL text in this image, including handwritten text, printed text, and any annotations. "
                    "Transcribe the text first, then answer any question(s) found in it. "
                    "If the image contains multiple questions (like a test paper with Q1, Q2, Q3...), "
                    "list and answer each question separately and clearly labeled. "
                    "Do NOT just describe the visual appearance of the image. "
                    "Focus on EXTRACTING and ACTING ON the content."
                )
                if att_data['ocr_text']:
                    system_prompt += f"\n\nOCR-EXTRACTED TEXT (may contain errors, cross-reference with the image):\n{att_data['ocr_text']}"
            
            messages = [SystemMessage(content=system_prompt)]

            for u_msg, a_msg in recent_history:
                messages.append(HumanMessage(content=u_msg))
                messages.append(AIMessage(content=a_msg))

            # Build the human message - multimodal if images are present
            if att_data['has_images']:
                content_parts = []
                if att_context:
                    content_parts.append({"type": "text", "text": f"{question}\n{att_context}"})
                else:
                    content_parts.append({"type": "text", "text": question})
                for img_uri in att_data['image_payloads']:
                    content_parts.append({"type": "image_url", "image_url": {"url": img_uri}})
                messages.append(HumanMessage(content=content_parts))
            else:
                final_question = question
                if att_context:
                    final_question = f"{question}\n{att_context}"
                messages.append(HumanMessage(content=final_question))

            chain = llm | StrOutputParser()
            answer = chain.invoke(messages)

            if session_id not in self.chat_history:
                self.chat_history[session_id] = []
            self.chat_history[session_id].append((question, answer))

            # Generate follow-up suggestions
            suggestions = self._generate_follow_up_suggestions(question, answer)

            return answer, sources, confidence, suggestions

        except Exception as e:
            err_msg = str(e)
            if "401" in err_msg or "unauthorized" in err_msg.lower():
                return "❌ Error: Invalid NVIDIA API Key. Please check your credentials.", [], 0.0, []
            elif "429" in err_msg or "rate limit" in err_msg.lower():
                return "⏳ Error: NVIDIA API Rate limit reached. Please try again in a few seconds.", [], 0.0, []
            elif att_data.get('has_images'):
                return "I'm having trouble reading this image clearly. Could you try a clearer photo, better lighting, or straighten the page?", [], 0.0, []
            else:
                return f"❌ Error: {err_msg}", [], 0.0, []

    def query_stream(self, question: str, session_id: str = "default", eli5_mode: bool = False, attachments: List[InlineAttachment] = None) -> Generator[str, None, None]:
        """Streaming query that yields SSE-formatted data events token-by-token."""
        # A user can submit a question while a newly uploaded document is still
        # being parsed/chunked.  Keep the request alive until the first
        # progressive embedding batch makes the index searchable instead of
        # immediately returning the misleading "no documents" response.
        wait_started = time.time()
        while self.vector_store is None and self.is_processing and time.time() - wait_started < 120:
            active_tasks = [task for task in self._processing_tasks.values() if task.status not in ("complete", "error")]
            stage = active_tasks[-1].stage_label if active_tasks else "Preparing your documents for search..."
            yield f"data: {json.dumps({'status': 'indexing', 'message': stage})}\n\n"
            time.sleep(0.5)

        context_str, sources, confidence, search_query = self._retrieve_context(question, session_id)

        # Process inline attachments
        att_data = self._process_attachments(attachments or [])
        att_context = att_data['text']

        # Check if we have stored image context from a previous upload in this session
        stored_image_ctx = self.image_context.get(session_id, "")
        has_stored_image = bool(stored_image_ctx)

        if context_str is None and not att_context and not att_data['has_images'] and not has_stored_image:
            yield f"data: {json.dumps({'token': 'No documents have been uploaded yet. Please upload PDF files first.', 'done': True, 'sources': [], 'confidence_score': 0.0, 'follow_up_suggestions': [], 'is_non_answer': True})}\n\n"
            return

        api_key = settings.NVIDIA_API_KEY
        if not api_key:
            yield f"data: {json.dumps({'token': 'NVIDIA API Key is missing.', 'done': True, 'sources': [], 'confidence_score': 0.0, 'follow_up_suggestions': [], 'is_non_answer': True})}\n\n"
            return

        source_type = "documents"
        
        # --- WEB SEARCH FALLBACK LOGIC ---
        # Skip web fallback if we have image context (from current or previous upload)
        if settings.ENABLE_WEB_FALLBACK and confidence < 0.75 and context_str and not att_context and not att_data['has_images'] and not has_stored_image:
            print(f"[RAGEngine] Confidence ({confidence:.2f}) < 0.75. Triggering web fallback.")
            yield f"data: {json.dumps({'status': 'searching', 'message': 'This does not seem to be covered in your documents - searching the web...'})}\n\n"
            
            web_context, web_sources = self._perform_web_search(question)
            if web_context:
                context_str = web_context
                sources = web_sources
                source_type = "web"
                system_prompt = (
                    "You are a helpful AI assistant. The user's question was not found in their documents, "
                    "so we performed a web search. Answer the user's question using ONLY the provided web search results. "
                    "Do not use your general knowledge. If the web results do not contain the answer, "
                    "say: 'I could not find this in your uploaded documents or verify it online. This may be outside the scope of what I know for certain.'\n\n"
                    f"WEB SEARCH RESULTS:\n{context_str}"
                )
            else:
                fallback_msg = "I could not find this in your uploaded documents or verify it online. This may be outside the scope of what I know for certain."
                yield f"data: {json.dumps({'token': fallback_msg, 'done': True, 'sources': [], 'confidence_score': 0.0, 'follow_up_suggestions': [], 'source_type': 'web', 'is_non_answer': True})}\n\n"
                return
        
        history = self.chat_history.get(session_id, [])
        recent_history = history[-5:]

        try:
            # Switch to vision model when images are present in THIS message
            model_name = settings.VISION_MODEL if att_data['has_images'] else settings.LLM_MODEL
            print(f"[RAGEngine] Using model: {model_name}")
            
            llm = ChatNVIDIA(
                model=model_name,
                nvidia_api_key=api_key,
                temperature=settings.LLM_TEMPERATURE,
                timeout=settings.LLM_TIMEOUT
            )

            if source_type == "documents":
                system_prompt = self._build_system_prompt(context_str if context_str else "", eli5_mode)
            
            # --- INJECT STORED IMAGE CONTEXT for follow-up questions ---
            if has_stored_image and not att_data['has_images']:
                source_type = "image"
                system_prompt += (
                    "\n\n--- PREVIOUSLY UPLOADED IMAGE CONTENT ---\n"
                    "The user previously uploaded an image in this conversation. "
                    "The extracted content from that image is provided below. "
                    "Use this content to answer the user's follow-up questions about the image. "
                    "This is a VALID source of information - do not say 'no answer found' if the answer "
                    "is present in this image content.\n\n"
                    f"{stored_image_ctx}\n"
                    "--- END IMAGE CONTENT ---"
                )
                print(f"[RAGEngine] Injected stored image context ({len(stored_image_ctx)} chars) for session '{session_id}'")

            # Add explicit image reading instructions when images are present
            if att_data['has_images']:
                system_prompt += (
                    "\n\nCRITICAL IMAGE READING INSTRUCTIONS:\n"
                    "1. TRANSCRIBE FIRST: Read and transcribe ALL text in this image EXACTLY as written, "
                    "line by line. Include every word, number, symbol, and equation you can see.\n"
                    "2. DO NOT DESCRIBE: Do NOT describe the appearance, handwriting style, ink color, "
                    "paper type, or visual layout of the image. Do NOT use phrases like 'the image shows', "
                    "'the notes appear to be', 'written in cursive', 'red ink', or 'well-organized'.\n"
                    "3. CONTENT ONLY: Focus EXCLUSIVELY on what the text SAYS, not what it LOOKS LIKE.\n"
                    "4. MULTI-QUESTION HANDLING: If the image contains multiple questions (like a test paper "
                    "with Q1, Q2, Q3...), transcribe each question exactly, then answer each one separately "
                    "with clear labels (Q1, Q2, etc.).\n"
                    "5. HANDWRITING: For handwritten text, do your best to read every word. If a word is "
                    "unclear, provide your best guess in [brackets].\n"
                    "6. STRUCTURE: Preserve the structure of the original text (numbered lists, headings, "
                    "sections) in your transcription.\n"
                    "7. THEN ANSWER: After transcribing, answer or solve all questions found in the image."
                )
                if att_data['ocr_text']:
                    system_prompt += (
                        f"\n\nOCR-EXTRACTED TEXT (use this as a reference to help read the image accurately, "
                        f"but cross-reference with what you actually see in the image):\n{att_data['ocr_text']}"
                    )
            
            messages = [SystemMessage(content=system_prompt)]

            for u_msg, a_msg in recent_history:
                messages.append(HumanMessage(content=u_msg))
                messages.append(AIMessage(content=a_msg))

            # Build the human message - multimodal if images are present
            if att_data['has_images']:
                content_parts = []
                if att_context:
                    content_parts.append({"type": "text", "text": f"{question}\n{att_context}"})
                else:
                    content_parts.append({"type": "text", "text": question})
                for img_uri in att_data['image_payloads']:
                    content_parts.append({"type": "image_url", "image_url": {"url": img_uri}})
                messages.append(HumanMessage(content=content_parts))
            else:
                final_question = question
                if att_context:
                    final_question = f"{question}\n{att_context}"
                messages.append(HumanMessage(content=final_question))

            full_answer = ""
            for chunk in llm.stream(messages):
                token = chunk.content if hasattr(chunk, 'content') else str(chunk)
                if token:
                    # Some hosted models can enter a repetition loop, especially while
                    # emitting LaTeX. Stop before the repeated block reaches the user.
                    candidate = full_answer + token
                    normalized = re.sub(r'\s+', ' ', candidate).strip()
                    repeated = False
                    if len(normalized) > 360:
                        tail = normalized[-120:]
                        repeated = normalized.count(tail) >= 3
                    if repeated:
                        print('[RAGEngine] Stopped runaway repeated generation.')
                        warning = '\n\nThe derivation began repeating, so I stopped here. Please retry this problem for a fresh verified solution.'
                        full_answer = full_answer.rstrip() + warning
                        yield f"data: {json.dumps({'token': warning, 'done': False})}\n\n"
                        break
                    full_answer += token
                    yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"

            # --- PERSIST IMAGE CONTEXT for follow-up questions ---
            if att_data['has_images'] and full_answer.strip():
                # Store the LLM's transcription/analysis + OCR text as session image context
                image_content_parts = []
                if att_data['ocr_text']:
                    image_content_parts.append(f"[OCR Extracted Text]:\n{att_data['ocr_text']}")
                image_content_parts.append(f"[Vision Model Analysis]:\n{full_answer}")
                self.image_context[session_id] = "\n\n".join(image_content_parts)
                print(f"[RAGEngine] Stored image context for session '{session_id}' ({len(self.image_context[session_id])} chars)")

            # Save to history
            if session_id not in self.chat_history:
                self.chat_history[session_id] = []
            self.chat_history[session_id].append((question, full_answer))

            # --- NON-ANSWER DETECTION ---
            # Don't flag as non-answer if we have image context (current or stored)
            is_non = _is_non_answer(full_answer) if not (att_data['has_images'] or has_stored_image) else False
            if is_non:
                print(f"[RAGEngine] Detected non-answer response. Suppressing metadata.")

            # Generate follow-up suggestions only for real answers
            suggestions = [] if is_non else self._generate_follow_up_suggestions(question, full_answer)

            # Send final event with metadata
            sources_data = [] if is_non else [s.model_dump() for s in sources]
            final_confidence = 0.0 if is_non else confidence
            # If answer came from image context, use a special source_type
            if att_data['has_images'] or has_stored_image:
                source_type = "image"
            yield f"data: {json.dumps({'token': '', 'done': True, 'sources': sources_data, 'confidence_score': final_confidence, 'follow_up_suggestions': suggestions, 'source_type': source_type, 'is_non_answer': is_non})}\n\n"
            return

        except Exception as e:
            err_msg = str(e)
            if att_data.get('has_images'):
                error_text = "I'm having trouble reading this image clearly. Could you try a clearer photo, better lighting, or straighten the page?"
            elif "401" in err_msg or "unauthorized" in err_msg.lower():
                error_text = "❌ Error: Invalid NVIDIA API Key. Please check your credentials."
            elif "429" in err_msg or "rate limit" in err_msg.lower():
                error_text = "⏳ Error: NVIDIA API Rate limit reached. Please try again in a few seconds."
            else:
                error_text = f"❌ Error: {err_msg}"
            print(f"[RAGEngine] Stream error: {err_msg}")
            # Always terminate an SSE request with a visible error event.  The
            # previous path only logged the exception, which looked like an
            # empty assistant message in the client.
            yield f"data: {json.dumps({'token': error_text, 'done': True, 'sources': [], 'confidence_score': 0.0, 'follow_up_suggestions': [], 'is_non_answer': True})}\n\n"
            return
        if filename not in self.processed_files:
            return False

        with self._lock:
            if not self.vector_store or not hasattr(self.vector_store, 'docstore'):
                return False

            # Collect all docs NOT belonging to this file
            remaining_docs = []
            docstore = self.vector_store.docstore._dict
            for doc_id, doc in docstore.items():
                if doc.metadata.get("source_filename") != filename:
                    remaining_docs.append(doc)

            # Rebuild index
            self.processed_files.discard(filename)
            self.file_details.pop(filename, None)

            if remaining_docs:
                self.vector_store = FAISS.from_documents(remaining_docs, self.embeddings)
                self.total_chunks = len(remaining_docs)
                self._save_vector_store()
            else:
                self.vector_store = None
                self.total_chunks = 0
                if (self.index_path / "index.faiss").exists():
                    try:
                        os.remove(self.index_path / "index.faiss")
                        os.remove(self.index_path / "index.pkl")
                    except Exception:
                        pass

        return True

    # ----------------------------------------------------------
    # PER-FILE SUMMARIZATION
    # ----------------------------------------------------------
    def summarize_file(self, filename: str) -> str:
        """Summarizes a file by retrieving its chunks and calling the LLM."""
        if not self.vector_store or filename not in self.processed_files:
            return "File not found in the index."

        # Gather all chunks for this file
        chunks_text = []
        with self._lock:
            docstore = self.vector_store.docstore._dict
            for doc_id, doc in docstore.items():
                if doc.metadata.get("source_filename") == filename:
                    chunks_text.append(doc.page_content)

        if not chunks_text:
            return "No content found for this file."

        # Limit to first ~8000 chars to avoid token limits
        combined = "\n\n".join(chunks_text)[:8000]

        try:
            api_key = settings.NVIDIA_API_KEY
            llm = ChatNVIDIA(
                model=settings.LLM_MODEL,
                nvidia_api_key=api_key,
                temperature=0.3,
                timeout=settings.LLM_TIMEOUT
            )
            messages = [
                SystemMessage(content="You are an expert summarizer. Provide a comprehensive yet concise summary of the following document content. Use bullet points, highlight key topics, and keep it well-structured with markdown formatting."),
                HumanMessage(content=f"Summarize this document ({filename}):\n\n{combined}")
            ]
            chain = llm | StrOutputParser()
            return chain.invoke(messages)
        except Exception as e:
            return f"Error generating summary: {e}"


# Global singleton engine
rag_engine = RAGEngine()
