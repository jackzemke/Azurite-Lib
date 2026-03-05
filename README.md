# Azurite Archive Assistant (AAA)

A cite-first, retrieval-augmented knowledge system for engineering and construction projects. AAA makes past work instantly discoverable via natural language, with strict provenance on every answer and safe logging practices. Built for accuracy, privacy, and operational reliability.

**Target:** 2/18 Pilot Stabilization — Make AAA reliable for non-technical users. Retrieval quality > new features.

- Backend: FastAPI (Python 3.10+) + `llama-cpp-python` for local inference
- Frontend: React + TypeScript + Vite
- Vector DB: ChromaDB (embedded, persistent)
- LLM: Llama-3.2-3B-Instruct (Q6_K, GGUF), optimized for RTX 4090; deterministic temperature=0.0
- Embeddings: `nomic-ai/nomic-embed-text-v1.5` via sentence-transformers (task-prefixed query/document embeddings)
- ERP Integration: Ajera unified JSON (77MB, 12,529 projects) for employee-scoped filtering

## Why AAA
- Citation-first answers: Always returns document evidence `(project_id, file_path, page, chunk_id)`
- User-scoped search: Employee filter uses Ajera timesheets to show only relevant projects
- Semantic-first chunking: Engineering docs are structured; AAA splits by headings before windowing
- Query expansion: Synonyms and doc-type hints improve vague query results
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
- Embeddings (`nomic-ai/nomic-embed-text-v1.5` via sentence-transformers): Task-optimized embeddings with separate query/document prefixes
- ERP Integration (Ajera): User-scoped filtering (employee→projects) for safer, more relevant results
- Frontend (React + Vite): Search and Upload experiences with a professional UX and progress feedback

## Features
- Citation provenance triple: `(project_id, file_path, page, chunk_id)` with every answer
- Hybrid retrieval: Structured filters (projects, employees) + semantic search over document chunks
- Query expansion: Automatic synonym expansion and doc-type boosting for vague queries
- Diversity filtering: Max 2 chunks per file, max 4 from same doc family (prevents invoice flooding)
- Semantic-first chunking with fallback windowing (500 tokens, 100 overlap)
- OCR trigger: If extracted text length < `ocr.min_text_length` (default 100), Tesseract OCR is run
- Stub mode: Deterministic test responses when model file is missing
- Security-first logging: Metadata-only; no raw document text is logged
- Async upload + ingest: Directory-based uploads with background processing via Redis Queue
- Employee filter: Uses Ajera timesheet data to scope searches to relevant projects
- Simple UI: Chat-first interface with optional employee/project filters

## Data Flow
- Ingestion: Upload → Extract → Normalize → Chunk → Embed → Index (with metadata)
- Query: User context → Filter projects → Semantic search → LLM synthesis → Citations
- Fallback: No docs found → Return Ajera project IDs + database locations

## Project Structure
```
app/
   backend/
      app/
         api/            # FastAPI routers (upload, ingest, query, jobs, ajera, health)
         core/           # Extractors, chunker, embedder, indexer, llm_client, query_expander
         prompts/        # Prompt templates (strict JSON for QA)
         schemas/        # Pydantic models
      config.yaml       # Absolute paths and runtime config
      requirements.txt
   frontend/
      src/
         pages/          # SearchPage, UploadPage
         components/     # WelcomeModal, HelpModal
      package.json
   scripts/             # CLI tools for ingestion, debugging, project management
data/
   raw_docs/{project_id}/   # Uploaded documents
   chunks/{project_id}/     # Processed chunks (JSON)
   index/chroma/            # ChromaDB persistent storage
   models/                  # GGUF models (not in git)
   logs/                    # Ingestion reports
   ajera_unified.json       # Ajera timesheet data (77MB)
```

## Setup
### Prerequisites
- Python 3.10+
- Node.js 18+
- Tesseract OCR (`tesseract` command on PATH)
- Redis (optional, required for async job queue)
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
```bash
source .venv/bin/activate
cd app/backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend (Vite)
```bash
cd app/frontend
npm run dev  # http://localhost:5173
```

### With Async Job Queue (Recommended)
```bash
# Terminal 1: Start Redis
redis-server

# Terminal 2: Start RQ worker
source .venv/bin/activate
python app/scripts/run_worker.py

# Terminal 3: Start backend
source .venv/bin/activate && cd app/backend
uvicorn app.main:app --reload --port 8000

# Terminal 4: Start frontend
cd app/frontend && npm run dev
```

**Note:** Without Redis, uploads still work but ingestion runs synchronously (blocks until complete).

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
```bash
# 1) Start backend and frontend (two terminals)
source .venv/bin/activate && cd app/backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
cd app/frontend && npm run dev

# 2) Open http://localhost:5173 and use the Upload button to add a project folder

# 3) Query via CLI (bypasses LLM, shows raw retrieval)
python app/scripts/debug_query.py --query "pipe diameter" --project demo_project
```

## Project Management
### List Projects
```bash
python app/scripts/delete_project.py --list
```
Shows projects on filesystem and in ChromaDB with chunk counts.

### Delete a Project
```bash
# Dry run (see what would be deleted)
python app/scripts/delete_project.py "Project Name" --dry-run

# Actually delete (filesystem + ChromaDB)
python app/scripts/delete_project.py "Project Name"
```

### Debug ChromaDB
```bash
python app/scripts/debug_chromadb.py
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

### Async Ingestion (Recommended for Large Projects)
For projects with many files, use the async ingestion endpoint that processes in the background:

1. **Start Redis** (required for job queue):
```bash
# Option 1: Docker
docker run -d -p 6379:6379 redis

# Option 2: System package (Ubuntu/Debian)
sudo apt install redis-server && redis-server
```

2. **Start RQ Worker** (in a separate terminal):
```bash
source .venv/bin/activate
python app/scripts/run_worker.py
```

3. **Upload and Ingest**:
- Frontend: Use the Upload page - it automatically uses async ingestion with real-time progress
- API: `POST /api/v1/projects/{project_id}/ingest/async` returns immediately with a `job_id`
- Poll `GET /api/v1/jobs/{job_id}` for progress updates

**Job Queue API Endpoints:**
- `GET /api/v1/jobs/{job_id}` — Get job status and progress
- `POST /api/v1/jobs/{job_id}/cancel` — Cancel a queued job
- `GET /api/v1/jobs` — List all jobs with optional filtering
- `GET /api/v1/jobs/queue/stats` — Queue statistics
- `GET /api/v1/jobs/queue/health` — Health check

**Fallback Mode:** If Redis is not available, ingestion runs synchronously (blocking). The frontend will still work but won't show real-time progress.

### Ingestion reports
- Stored under `data/logs/ingest_report_{project_id}.json`
- Includes document counts, errors, duplicates, and chunk statistics

## Querying the System
### Employee-Scoped Queries
- Select an employee from the dropdown to filter results to their project history
- Uses Ajera timesheet data (solid coverage: hours worked per project)
- If no documents match, AAA returns a helpful message about the employee's projects

### API Endpoints
**Core:**
- `GET /api/v1/health` — Server readiness and stub-mode status
- `POST /api/v1/query` — RAG query; returns `answer`, `citations`, `confidence`, `stub_mode`
- `GET /api/v1/projects` — List indexed projects with document/chunk counts

**Upload & Ingest:**
- `POST /api/v1/projects/{project_id}/upload` — Upload project documents
- `POST /api/v1/projects/{project_id}/ingest` — Synchronous ingestion
- `POST /api/v1/projects/{project_id}/ingest/async` — Async ingestion (returns job_id)

**Job Queue:**
- `GET /api/v1/jobs/{job_id}` — Get job status and progress
- `POST /api/v1/jobs/{job_id}/cancel` — Cancel a queued job
- `GET /api/v1/jobs` — List all jobs
- `GET /api/v1/jobs/queue/stats` — Queue statistics

**Ajera:**
- `GET /api/v1/employees` — List employees (from Ajera timesheets)
- `GET /api/v1/employees/{id}` — Get employee details
- `GET /api/v1/employees/{id}/projects` — Get employee's project history
- `GET /api/v1/departments` — List department codes (inferred from file IDs)

### Citations
- Mandatory provenance: `(project_id, file_path, page, chunk_id)` per result
- The prompt enforces strict JSON output; Pydantic validates on the backend
- Empty citations + `confidence: "low"` when no evidence found (no hallucination)

## Frontend UI
- **Simple chat-first interface:** One text box for questions, optional filters
- **Employee filter:** Dropdown to scope queries to an employee's project history (Ajera timesheets)
- **Project filter:** Multi-select to limit search to specific indexed projects
- **Upload page:** Directory picker with batched uploads and async processing progress
- **Welcome modal:** Tips for new users; help button to reopen
- **Sticky header/footer:** Always-visible navigation and input

## Retrieval Tuning
Key levers in `config.yaml` and code:

| Lever | Current | Location |
|-------|---------|----------|
| Chunk size | 500 tokens | `config.yaml` |
| Overlap | 100 tokens | `config.yaml` |
| top_k | 6 | `config.yaml` |
| Diversity | max 2/file, 4/family | `indexer.py` |
| Doc type boost | 0.05 distance reduction | `indexer.py` |
| Query expansion | 3 synonyms/keyword | `query_expander.py` |

### Debug Retrieval
```bash
# See raw retrieval without LLM
python app/scripts/debug_query.py --query "who was the client" --project "Acomita Day School"
```

## Testing & Validation
```bash
# All tests
pytest -v

# Retrieval quality tests (vague queries)
pytest tests/test_retrieval_quality.py -v

# FastAPI query integration tests
pytest tests/test_query_endpoint.py -v

# Unit tests for chunker
pytest tests/test_chunker.py -v
```

### Retrieval Quality Test Cases
These should pass (`tests/test_retrieval_quality.py`):
- `"who was the client"` → returns results, contract in top 2
- `"summary"` → returns results with distance < 0.5
- `"what is this project about"` → returns relevant results
- Diversity: max 2 chunks per file, max 4 from same doc family

## Troubleshooting
- **Model path missing** → Backend logs show `stub_mode: true`; download model or continue in stub mode
- **GPU issues** → Set `model.n_gpu_layers: 0` in `config.yaml`
- **OCR fails silently** → Ensure `tesseract` is installed; check with `tesseract --version`
- **Redis not running** → Ingestion works but runs synchronously (no progress updates)
- **Absolute paths** → Verify `config.yaml` paths after moving hosts or container mounts
- **Frontend API URL** → Set `VITE_API_URL` to backend address
- **ChromaDB telemetry warnings** → Cosmetic; doesn't affect functionality
- **Poor retrieval results** → Use `debug_query.py` to see raw distances; tune chunk size or query expansion

## Security & Privacy
- Logs store metadata only (e.g., `chunk_id`, `project_id`, `query`, `elapsed_ms`, `confidence`)
- Raw document text is never logged
- Employee-scoped search prevents cross-project leakage
- Ajera data loaded from local JSON (no live database connection required)

## Acceptance Criteria
- [x] Citations always returned (file + page + chunk_id)
- [x] Logs contain no raw document text
- [x] "Not found" response when no evidence (no hallucination)
- [x] Works in stub mode (CI/CD friendly)
- [x] Async job queue for large uploads
- [x] Employee filter using Ajera timesheets
- [x] Query expansion for vague queries
- [x] Diversity filtering (no duplicate citations)
- [ ] Graceful "I couldn't find that" messaging (in progress)

## Roadmap
- ~~Async ingestion job queue~~ ✓ Implemented with Redis Queue (RQ)
- ~~Employee-scoped filtering~~ ✓ Using Ajera timesheet data
- ~~Query expansion~~ ✓ Synonym expansion and doc-type hints
- Job recovery UI (list/resume jobs after tab close)
- PDF citation previews in the UI
- Ajera project linking wizard (manual mapping for non-matching folder names)
- Parallel PDF extraction for faster ingestion

## References
- `DECISIONS.md` — Architectural decisions and tradeoffs
- `CHANGELOG.md` — Release notes
- `INGESTION_CHECKLIST.md` — Operational checklist for new projects
- `.github/copilot-instructions.md` — AI coding agent context
