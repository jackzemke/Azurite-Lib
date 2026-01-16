# Azurite Archive Assistant (AAA)

A cite-first, retrieval-augmented knowledge system for engineering and construction projects. AAA makes past work instantly discoverable via natural language, with strict provenance on every answer and safe logging practices. Built for accuracy, privacy, and operational reliability.

- Backend: FastAPI (Python 3.10+) + `llama-cpp-python` for local inference
- Frontend: React + TypeScript + Vite
- Vector DB: ChromaDB (embedded, persistent)
- LLM: Llama-3.2-3B-Instruct (Q6_K, GGUF), optimized for RTX 4090; deterministic temperature=0.0
- Embeddings: `sentence-transformers` all-MiniLM-L6-v2 (384-d)
- ERP Integration: Ajera (SQL Server via `pyodbc`) for user-scoped project filtering

## Why AAA
- Citation-first answers: Always returns document evidence `(project_id, file_path, page, chunk_id)`
- User-scoped search: Respects employee project history to reduce noise and leakage
- Semantic-first chunking: Engineering docs are structured; AAA splits by headings before windowing
- Stub-mode reliability: Gracefully degrades when local model is unavailable (CI/CD friendly)
- Privacy by design: Logs metadata only; never logs raw document text

## Table of Contents
- Overview
- Architecture
- Features
- Data Flow
- Project Structure
- Setup
- Configuration
- Development
- Running
- Ingestion Workflows
- Querying the System
- Frontend UI
- Testing & Validation
- Troubleshooting
- Security & Privacy
- Acceptance Criteria
- Roadmap

## Overview
AAA eliminates tribal knowledge barriers by making prior project documents searchable with grounded citations, combining structured ERP context with unstructured content.

Primary use cases:
- Engineers: e.g., "What was the pipe burial depth on Las Cruces Community Center?"
- Marketing/BD: e.g., "Show Transit Authority projects from the last 3 years with similar scope"
- Fallback: If docs aren’t indexed, return project IDs and database locations to guide users

## Architecture
- Backend (`FastAPI`): Ingestion, embedding, indexing, and query orchestration
- Vector Index (`ChromaDB`): Persistent local ANN index (HNSW) with project/employee metadata
- LLM (`llama-cpp-python`): Strict JSON outputs, deterministic with temperature 0.0
- Embeddings (`sentence-transformers`): Compact sentence vectors for fast similarity search
- ERP Integration (Ajera): User-scoped filtering (employee→projects) for safer, more relevant results
- Frontend (React + Vite): Search and Upload experiences with a professional UX and progress feedback

## Features
- Citation provenance triple: `(project_id, file_path, page, chunk_id)` with every answer
- Hybrid retrieval: Structured filters (projects) + semantic search over document chunks
- Semantic-first chunking with fallback windowing (500 tokens, 100 overlap)
- OCR trigger: If extracted text length < `ocr.min_text_length` (default 100), Tesseract OCR is run
- Stub mode: Deterministic test responses when model file is missing
- Security-first logging: Metadata-only; no raw document text is logged
- Upload + ingest: Directory-based uploads, auto-detect project ID from folder name
- Rebranded frontend: Azurite Archive Assistant (AAA) with onboarding modal and improved UX

## Data Flow
- Ingestion: Upload → Extract → Normalize → Chunk → Embed → Index (with metadata)
- Query: User context → Filter projects → Semantic search → LLM synthesis → Citations
- Fallback: No docs found → Return Ajera project IDs + database locations

## Project Structure
```
app/
   backend/
      app/
         api/            # FastAPI routers (upload, ingest, query, health)
         core/           # Extractors, chunker, embedder, indexer, llm_client
         prompts/        # Prompt templates (strict JSON for QA)
         schemas/        # Pydantic models
      config.yaml       # Absolute paths and runtime config
      requirements.txt
   frontend/
      src/              # React + Vite UI
      package.json
scripts/              # CLI tools for ingestion and evaluation
data/
   raw_docs/{project_id}/
   chunks/{project_id}/
   embeddings/
   index/chroma/
   models/            # GGUF models (not in git)
   logs/
```

## Setup
### Prerequisites
- Python 3.10+
- Node.js 18+
- Tesseract OCR (`tesseract` command on PATH)
- NVIDIA GPU recommended (RTX 4090), CPU works with reduced performance

### Create Python environment
```
python -m venv .venv
source .venv/bin/activate
pip install -r app/backend/requirements.txt
```

### Install frontend dependencies
```
cd app/frontend
npm install
```

### Download the model (optional for stub mode)
- Model file path: `data/models/Llama-3.2-3B-Instruct-Q6_K.gguf`
- If missing, AAA runs in stub mode and returns deterministic test responses
```
bash scripts/download_model.sh
```

## Configuration
- All paths in `app/backend/config.yaml` are absolute; update when deploying to new hosts
- Key settings:
   - `model.path`: Absolute path to the GGUF model file
   - `model.n_gpu_layers`: Set to 0 if GPU is unavailable
   - `index.path`: Persistent Chroma index location (absolute)
   - `ocr.min_text_length`: Threshold to trigger OCR in PDFs
   - `logging.*`: Ensure metadata-only logging (no raw text)

## Development
### Backend (FastAPI)
```
source .venv/bin/activate
cd app/backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend (Vite)
```
cd app/frontend
npm run dev  # http://localhost:5173
```

### Environment variables
- `VITE_API_URL=http://localhost:8000` for the frontend to reach the backend
- Configure in `app/frontend/.env` or your shell environment

## Running
### Docker Compose (with GPU)
```
docker-compose up --build
# Tail backend logs
docker-compose logs -f backend
```
- If GPU is unavailable, set `model.n_gpu_layers: 0` in `config.yaml`

### Quickstart
```
# 1) Start backend and frontend (two terminals)
source .venv/bin/activate && cd app/backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
cd app/frontend && npm run dev

# 2) Load sample data
bash scripts/load_sample_data.sh

# 3) Ingest documents (demo)
python scripts/ingest_cli.py --project demo_project

# 4) Query via CLI
python scripts/debug_query.py --query "pipe diameter" --project demo_project
```

## Ingestion Workflows
### Upload
- Directory upload is supported; AAA auto-detects `project_id` from folder name
- Files are persisted under `data/raw_docs/{project_id}/` with subdirectory structure preserved

### Ingest (v2)
- Enhanced pipeline with validation, semantic chunking, embeddings, indexing, and detailed reports
- Indexer stores metadata required for citation provenance
```
python scripts/ingest_cli.py --project <project_id>
```

### Ingestion reports
- Stored under `data/logs/ingest_report_{project_id}.json`
- Includes document counts, errors, duplicates, and chunk statistics

## Querying the System
### User-scoped queries
- Provide `employee_id` to filter results to that employee’s project history (Ajera integration)
- If no documents match, AAA returns project metadata from Ajera as a fallback

### API endpoints
- `GET /api/v1/health` — server readiness and stub-mode status
- `POST /api/v1/projects/{project_id}/upload` — upload project documents (directory-aware)
- `POST /api/v1/ingest` — run ingestion for a given `project_id`
- `POST /api/v1/query` — RAG query; returns `answer`, `citations`, `confidence`, and `stub_mode`

### Citations
- Mandatory provenance triple: `(project_id, file_path, page, chunk_id)` per result
- The prompt enforces strict JSON output and Pydantic validation on the backend

## Frontend UI
- Rebranded to Azurite Archive Assistant (AAA); gradient purple/indigo theme
- Welcome modal with tips and a help button to reopen
- SearchPage: Intent-aware empty state with example queries; viewport-filling layout
- UploadPage: Simplified zero-input directory selection, robust progress feedback (bytes, files, elapsed, ETA, staged processing), and clear success/error states

## Testing & Validation
```
# All tests
pytest -v

# Unit tests for chunker
pytest tests/test_chunker.py -v

# FastAPI query integration tests
pytest tests/test_query_endpoint.py -v

# Coverage (backend core)
pytest --cov=app.backend.core
```

## Troubleshooting
- Model path missing → Backend logs show `stub_mode: true`; download model or continue in stub mode
- GPU issues → Set `model.n_gpu_layers: 0` in `config.yaml`
- OCR fails silently → Ensure `tesseract` is installed; check with `tesseract --version`
- Chroma telemetry → Disabled by default; ensure no outbound telemetry in production
- Absolute paths → Verify `config.yaml` paths after moving hosts or container mounts
- Frontend API URL → Set `VITE_API_URL` to backend address
- Docker GPU runtime → Requires NVIDIA Container Toolkit

## Security & Privacy
- Logs store metadata only (e.g., `chunk_id`, `project_id`, `query`, `elapsed_ms`, `confidence`)
- Raw document text is never logged
- User-scoped search prevents cross-project leakage

## Acceptance Criteria
- Citations always returned (file + page + chunk_id)
- Logs contain no raw document text
- “Not found” response when no evidence (no hallucination)
- Unit tests for core logic (70%+ coverage target)
- Integration test for API endpoint
- Works in stub mode (CI/CD friendly)

## Roadmap
- Real-time ingestion stage streaming (SSE/WebSockets)
- PDF citation previews in the UI
- More precise token counting (migrate to `tiktoken`)
- Expanded normalization (units, dates) for richer search facets

## References
- `DECISIONS.md` — Architectural decisions and tradeoffs
- `CHANGELOG.md` — Release notes (latest: 0.2.0, rebranding and UX overhaul)
- `INGESTION_CHECKLIST.md` — Operational checklist for new projects
