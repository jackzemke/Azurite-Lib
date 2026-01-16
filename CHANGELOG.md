# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-01-16

### Rebranding
- **Renamed from "ProjectMind" to "Azurite Archive Assistant (AAA)"**
- New branding throughout frontend with 💎 icon
- Updated page title and favicon

### Added

#### Frontend - User Experience Overhaul
- **Welcome Modal** - First-time user onboarding with dismissible popup
  - Shows tips for best results and example queries
  - "Don't show again" option with localStorage persistence
  - Help button (?) in header to re-open anytime
- **Redesigned Upload Flow** - Zero-input document ingestion
  - Single-click folder selection (directory upload only)
  - Auto-detects project name from folder
  - Extracts project IDs from folder names (e.g., "(1430152)")
  - Combined upload + ingest in one seamless flow
  - Animated progress indicators for upload and processing stages
  - Clear success/error feedback with actionable next steps
- **Improved Empty State** - Example queries and onboarding tips
- **Chat Interface Improvements**
  - Multi-stage loading indicators (embedding → searching → processing → synthesizing)
  - Enhanced citation display with project badges

#### Backend - Q&A Quality Improvements
- **MMR Diversity Retrieval** - Maximal Marginal Relevance for diverse citations
- **Citation Deduplication** - No more repeated sources in answers
- **Intent-Aware Query Expansion** - Better understanding of user questions
- **Enhanced QA Prompt** - Improved SMA company context and answer formatting
- **Disabled ChromaDB Telemetry** - Cleaner logs, no external calls
- **Reduced LLM Verbosity** - Set `verbose=False` for cleaner output

#### Backend - Project ID Mapping Infrastructure
- **ProjectMapper** (`project_mapper.py`) - CSV-based ProjectKey ↔ FileID lookups
- **FileSystemProjectScanner** (`filesystem_scanner.py`) - Scans raw_docs for project folders
- **UnifiedProjectResolver** (`project_resolver.py`) - Combines all data sources
  - Resolves Ajera employee IDs → file system folders
  - Maps project keys to folder names for ChromaDB filtering
  - Supports employee-scoped queries

#### Backend - Enhanced Ingestion Pipeline
- **DocumentValidator** (`document_validator.py`) - Pre/post-extraction quality control
  - Quality classification: HIGH/MEDIUM/LOW/SKIP
  - Duplicate detection via content hashing
  - File validation (size limits, corruption detection)
- **EnhancedChunker** (`enhanced_chunker.py`) - Context-preserving chunking
  - Document type detection from filename
  - Context prefixes on chunks (document title, section, type)
  - Sentence-aware splitting
- **ingest_v2 Endpoint** - Full validation pipeline with detailed reports
  - `GET /projects/{id}/index/stats` - View indexing statistics
  - `DELETE /projects/{id}/index` - Clear project from ChromaDB

#### Data
- Added `data/mappings/project_lookup.csv` - 1,694 projects with ProjectKey, FileID, Description

### Changed
- Query endpoint now uses UnifiedProjectResolver for employee filtering
- Indexer metadata schema extended: file_id, project_key, document_title, section_header
- Upload endpoint accepts folder names as project IDs (URL-encoded)

### Fixed
- `.get()` error on string citations - Added defensive type checking
- ChromaDB telemetry errors causing log spam
- LLM verbose logging causing excessive output
- Same-document citation repetition

### Technical Debt Addressed
- Modular project ID resolution (no more hardcoded mappings)
- Separation of concerns: validation, chunking, indexing
- Graceful degradation when data sources unavailable

---

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
