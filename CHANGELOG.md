# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2025-11-14

### Added

#### Core Features
- Multi-format document ingestion (PDF, DOCX, XLSX, images)
- OCR support for scanned documents using Tesseract
- Semantic-first chunking with fallback to fixed-window
- Local LLM integration via llama-cpp-python
- Citation-aware Q&A (always returns file + page + chunk_id)
- Persistent Chroma vector DB
- React frontend with upload and search interfaces

#### Backend
- FastAPI REST API with OpenAPI docs
- Pydantic schemas for validation
- PDF text extraction with pdfplumber
- DOCX text extraction with python-docx
- Image OCR with pytesseract
- Text normalization (dates, units, numbers)
- Sentence-transformers embeddings (all-MiniLM-L6-v2)
- ChromaDB indexing with cosine similarity
- Llama-3.2-3B-Instruct support (gguf quantized)
- Stub mode for testing without model file

#### Frontend
- React + TypeScript + Vite
- Search page with query input
- Upload page with file selection and ingestion trigger
- Result cards with citations
- Citation click handler (placeholder for PDF viewer)

#### Infrastructure
- Docker Compose with GPU support
- Dockerfiles for backend and frontend
- Config file (config.yaml) for all parameters
- Logging (queries, ingestion, errors)
- Health check endpoint

#### CLI Tools
- `ingest_cli.py` - Command-line ingestion
- `eval_cli.py` - Evaluation against ground truth

#### Testing & Evaluation
- Unit tests for chunker
- Integration test for query endpoint
- Unit test for PDF extractor
- Ground truth JSONL with sample queries
- Evaluation metrics script (citation accuracy, latency)

#### Documentation
- Comprehensive README with setup and usage
- DECISIONS.md with design rationale
- INGESTION_CHECKLIST.md with validation steps
- Inline code documentation and TODOs

### Non-Negotiable Requirements Met
- ✅ Multi-format ingestion
- ✅ Citations on all answers (file, page, chunk_id)
- ✅ Local LLM (with stub mode fallback)
- ✅ React UI
- ✅ Persistent index
- ✅ Test coverage (core modules)
- ✅ Docker Compose
- ✅ Security (no raw text in logs)
- ✅ "Not found" responses when no evidence

### Known Limitations
- Table parsing is basic (no complex nested tables)
- OCR accuracy depends on scan quality (85-95%)
- Single-project queries only (no cross-project search yet)
- PDF viewer integration is placeholder (not fully implemented)
- No human-in-the-loop validation UI yet

### TODO (Future Enhancements)
- Advanced table extraction (camelot-py, tabula-py)
- Hybrid search (Elasticsearch + semantic)
- Cross-encoder reranking
- Multi-modal support (CLIP, LLaVA for diagrams)
- Human validation UI for extracted facts
- Cloud LLM pilot (GPT-4 comparison)
- Multi-user authentication
- Cross-project search
- Streaming LLM responses
- Prompt caching
