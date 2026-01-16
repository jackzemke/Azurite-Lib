# AI Coding Agent Instructions

## System Overview

**ProjectMind** is a project knowledge retrieval system for an engineering/construction firm. It eliminates tribal knowledge barriers by making past project data instantly accessible through natural language queries. The architecture follows a RAG (Retrieval-Augmented Generation) pipeline with strict citation requirements—**never hallucinate without source**.

### Business Problem
Engineers and marketing staff struggle to find relevant past work due to:
- Complex, hard-to-navigate file storage systems
- Tribal knowledge locked in individual employees' heads
- Time pressure during proposal writing and solution design

### Core Use Cases
1. **Engineers**: "What was the pipe burial depth on Las Cruces Community Center?" → System searches Jane Doe's projects, returns answer with citations
2. **Marketing/BD**: "Show Transit Authority projects from last 3 years with similar scope" → System finds comparable work for proposals
3. **Fallback**: When documents don't exist, return project IDs and database locations to guide users

### Key Features
- **User-scoped search**: Queries automatically filtered to employee's project history (via Ajera integration)
- **Semantic similarity**: Find projects by description/scope, not just keywords
- **Citation-first**: Always return source documents (project ID, file path, page number)
- **Hybrid retrieval**: Structured data (project IDs, locations) + unstructured data (document content)

**Core Components:**
- **Backend:** FastAPI (Python 3.10+) with llama-cpp-python for local LLM inference
- **Frontend:** React + TypeScript + Vite, styled with gradient purple/indigo theme
- **Vector DB:** ChromaDB (embedded, persistent at `data/index/chroma/`)
- **LLM:** Llama-3.2-3B-Instruct (Q6_K quantized, GGUF format) optimized for RTX 4090
- **Embeddings:** all-MiniLM-L6-v2 (384-dim, sentence-transformers)
- **ERP Integration:** Ajera SQL Server (via pyodbc) for employee-project mappings and time tracking

**Data Flow:** 
- **Ingestion:** Upload → Extract → Normalize → Chunk → Embed → Index (with project/employee metadata)
- **Query:** User context → Filter projects → Semantic search → LLM synthesis → Citations
- **Fallback:** No docs found → Return project IDs from Ajera + database locations

## Critical Project-Specific Patterns

### 1. Stub Mode Architecture
The system **gracefully degrades** when the LLM model file is missing (`data/models/Llama-3.2-3B-Instruct-Q6_K.gguf`). Check `LLMClient.is_stub_mode()` and return deterministic test responses. This enables CI/CD without large model downloads.

```python
# All responses must include stub_mode flag
response = QueryResponse(..., stub_mode=llm_client.is_stub_mode())
```

### 2. Semantic-First Chunking with Fallback
`Chunker` detects headings (ALL CAPS, numbered sections, keyword-based) and splits at semantic boundaries. If no headings found, falls back to fixed 500-token windows with 100-token overlap. See `app/backend/app/core/chunker.py` for patterns.

**Key:** Engineering docs have structure—exploit it before brute-force splitting.

### 3. Citation Provenance Triple
Every citation **must** include `(project_id, file_path, page, chunk_id)`. The LLM prompt (`app/backend/app/prompts/qa_prompt.txt`) enforces JSON output with mandatory citations. Parse and validate with Pydantic `Citation` model.

**Never return an answer without citations** unless explicitly "Not found in indexed documents".

### 4. Security-First Logging
**Log metadata only, never raw document text.** See `_log_query()` in `app/backend/app/api/query.py`:
- ✅ Log: `chunk_id`, `project_id`, `query`, `elapsed_ms`, `confidence`
- ❌ Never log: chunk text content, file contents

This is for privacy compliance (engineering docs may be sensitive).

### 5. User-Scoped Query with Ajera Integration
The `QueryRequest` model accepts `employee_id: str` (optional). When provided, the system:
1. Looks up employee's project history from Ajera time series data (`data/ajera_time_series.json`)
2. Filters ChromaDB search to only those projects
3. If no documents found, returns Ajera project IDs and locations as fallback

```python
# User-scoped query flow
employee_projects = ajera_data['employee_to_projects'][employee_id]['projects']
results = indexer.query(query_embedding, project_ids=employee_projects, top_k=6)
# If results empty: return project metadata from Ajera instead of "not found"
```

This prevents information leakage (employees only see their projects) and improves relevance (search smaller corpus).

### 6. OCR Triggering Logic
PDF extraction uses `pdfplumber`. If extracted text length < `config.yaml:ocr.min_text_length` (default 100), trigger Tesseract OCR. Check `PDFExtractor.extract()` for the decision flow.

### 7. Absolute Paths in Config
All paths in `config.yaml` are **absolute** (e.g., `/home/jack/lib/project-library/data/...`). This simplifies Docker volume mounts. Update paths when deploying to new environments.

### 8. Ajera Data Loading Strategy
Employee-project mappings are stored in `data/ajera_time_series.json` with structure:
```json
{
  "employee_to_projects": {
    "5712": {
      "name": "Jane Doe",
      "projects": ["33568", "12345"],
      "timeline": {"33568": [{"date": "2024-12-07", "hours": 5.0}]}
    }
  },
  "project_to_employees": { ... }
}
```

Load this on backend startup (cache in memory) for fast filtering. Refresh periodically via Ajera queries (daily/weekly batch job).

## Developer Workflows

### Starting Development Servers
```bash
# Backend (from project root)
source .venv/bin/activate
cd app/backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Frontend (separate terminal)
cd app/frontend
npm run dev  # Runs on http://localhost:5173
```

### Running Tests
```bash
# From project root
pytest -v                          # All tests
pytest tests/test_chunker.py -v   # Specific test
pytest --cov=app.backend.core     # With coverage
```

**Test Philosophy:** Unit tests for extractors/chunker/embedder (isolated), integration tests for API endpoints (full pipeline). See `tests/test_query_endpoint.py` for FastAPI `TestClient` patterns.

### CLI Workflows
```bash
# Ingest documents
python app/scripts/ingest_cli.py --project proj_demo

# Debug query logic (bypasses API)
python app/scripts/debug_query.py --query "pipe diameter" --project proj_demo

# E2E validation (health + query + ingestion)
python app/scripts/validate_e2e.py

# Evaluation against ground truth
python evaluation/eval_metrics.py --project proj_demo
```

### Docker Compose with GPU
```bash
docker-compose up --build  # Requires NVIDIA Container Toolkit
docker-compose logs -f backend
```

**GPU Note:** Check `deploy.resources` in `docker-compose.yml`. If GPU unavailable, set `model.n_gpu_layers: 0` in `config.yaml`.

## File Organization Conventions

### Data Persistence (`data/`)
```
data/
├── raw_docs/{project_id}/     # Uploaded documents
├── chunks/{project_id}/        # {chunk_id}.json files
├── embeddings/                 # {project_id}.parquet files
├── index/chroma/               # ChromaDB SQLite + HNSW index
├── models/                     # LLM GGUF files (not in git)
└── logs/                       # queries.log, ingest_report_{project}.json
```

**Important:** `data/models/` is excluded from git. Check README for model download instructions.

### Backend Structure
- `app/api/`: FastAPI routers (upload, ingest, query, health)
- `app/core/`: Business logic (extractors, chunker, embedder, indexer, llm_client)
- `app/prompts/`: Plain text prompt templates (`.txt` files, not Python)
- `app/schemas/`: Pydantic models for validation

### Frontend Structure
- `src/pages/`: SearchPage, UploadPage (main views)
- `src/components/`: ResultCard (reusable UI)
- `styles.css`: Global styles with custom scrollbars, gradient theme

## Integration Points

### Chroma Indexing
```python
# Upsert chunks (app/core/indexer.py)
indexer.upsert_chunks(chunks, embeddings)

# Query with project filtering
results = indexer.query(query_embedding, project_ids=["proj_demo"], top_k=6)
```

ChromaDB uses HNSW for approximate nearest neighbors. Indexed fields: `chunk_id`, `project_id`, `file_path`, `page_number`, `text`.

### LLM Client
```python
# app/core/llm_client.py
llm_output = llm_client.generate_json(prompt, max_tokens=512)
# Returns dict with keys: answer, citations, confidence
```

**Temperature is 0.0** for deterministic output. Increase if creative responses needed (unlikely for citation-heavy QA).

### Normalizer
Detects and normalizes dates (ISO 8601) and units (feet→meters, inches→cm). Returns `(normalized_text, metadata_dict)`. Store both in chunk metadata for future multi-modal search.

## Common Gotchas

1. **Model Path:** If backend logs show `stub_mode: true`, check `data/models/Llama-3.2-3B-Instruct-Q6_K.gguf` exists.
2. **CORS in Production:** `main.py` allows all origins (`allow_origins=["*"]`). Restrict in production.
3. **Token Counting:** Uses whitespace splitting (fast approximation). TODO: Migrate to `tiktoken` for accuracy.
4. **Frontend API URL:** Vite expects `VITE_API_URL=http://localhost:8000`. Update `.env` if backend port changes.
5. **Tesseract Dependency:** OCR fails silently if `tesseract-ocr` not installed. Check with `tesseract --version`.

## Architectural Decisions Reference

See `DECISIONS.md` for rationale behind:
- Why pdfplumber over PyMuPDF (table extraction, bounding boxes)
- Why ChromaDB over Qdrant (embedded, simpler for local-first)
- Why llama-cpp-python over vLLM (lower memory, better quantization)
- Prompt engineering strategy (strict JSON output)

## Acceptance Criteria Checklist

When implementing new features, ensure:
- [ ] Citations always returned (file + page + chunk_id)
- [ ] Logs contain no raw document text
- [ ] "Not found" response when no evidence (no hallucination)
- [ ] Unit tests for core logic (70%+ coverage target)
- [ ] Integration test for API endpoint
- [ ] Works in stub mode (CI/CD friendly)

## Key Files to Reference

- **Pipeline orchestration:** `app/backend/app/api/ingest.py` (full extract→index flow)
- **Query logic:** `app/backend/app/api/query.py` (RAG + LLM + validation)
- **Prompt template:** `app/backend/app/prompts/qa_prompt.txt` (LLM instructions)
- **Schema definitions:** `app/backend/app/schemas/models.py` (Pydantic models)
- **Config:** `app/backend/config.yaml` (all hyperparameters, paths)
- **Test examples:** `tests/test_chunker.py`, `tests/test_query_endpoint.py`
