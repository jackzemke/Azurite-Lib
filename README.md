# Azurite Archive Assistant (AAA)

RAG system for engineering project document retrieval. Natural language queries
return cited, verifiable answers with direct links to source files on the
network file server. No raw files are ever stored locally.

## Status
**Beta target: April 15, 2026**
Scope: PDF + DOCX, last 5 years of corpus, hybrid retrieval, cited answers,
Ajera integration for personnel queries.

LLaMA 3.2 3B for synthesis during beta. Claude API post-beta pending approval.
Cohere keys pending. 4.10 read access pending IT.

---

## Stack
| Component | Technology |
|---|---|
| Backend | FastAPI (Python 3.12) |
| Vector store | Weaviate (self-hosted, Docker) |
| Embeddings | Cohere Embed API |
| Reranking | Cohere Rerank API |
| LLM (beta) | LLaMA 3.2 3B Instruct (llama-cpp-python, Q6_K GGUF) |
| LLM (post-beta) | Claude API |
| Search | Weaviate hybrid (vector + BM25) |
| Frontend | React + TypeScript + Vite |
| ERP | Ajera (static JSON, 77MB, 12,529 projects) |
| Query routing | Rule-based classifier (no ML overhead) |

---

## Infrastructure
- **Workstation (3.11):** All services run here. NVIDIA GPU. 100GB drive, ~72GB free.
- **File server (4.10):** All raw documents live here permanently. Read-only mount.
- **Mock corpus:** `/mock_corpus` on 3.11 — used until 4.10 access is confirmed.
- **Docker:** All services containerized. Weaviate resource limits enforced.

---

## Hard Constraints
- **Never duplicate raw files.** Ingestion reads from 4.10, extracts text, stores
  only chunks + embeddings + file paths. Raw bytes never touch 3.11.
- **Storage is tight.** 72GB free. Every architectural decision accounts for this.
  Weaviate configured for minimal disk footprint.
- **Citations are mandatory.** Every answer includes `file://192.168.4.10/...`
  clickable links. No citations = low confidence response, not a hallucinated answer.

---

## Architecture

### Query flow
```
User query
  → Query classifier (DOCUMENT_QA | PERSONNEL | META_AGGREGATION)
  → DOCUMENT_QA: Cohere embed → Weaviate hybrid search → Cohere rerank → LLaMA synthesis
  → PERSONNEL: Ajera JSON lookup
  → META_AGGREGATION: Ajera JSON lookup (scoped, post-beta for complex aggregation)
  → Response with file:// citations
```

### Ingestion flow
```
Crawl 4.10 (read-only, PDF + DOCX only)
  → Extract text locally
  → Chunk
  → Send chunks to Cohere Embed API
  → Store in Weaviate: chunk text, embedding, file path, page, project ID, chunk ID
  → Raw files never leave 4.10
```

### Citation format
```
file://192.168.4.10/path/to/project/file.pdf
```
Rendered as clickable links in the frontend. Page number and chunk ID included.

---

## Project Structure
```
azurite-lib/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── query.py
│   │   │   ├── ingest.py
│   │   │   └── health.py
│   │   ├── core/
│   │   │   ├── crawler.py          # Crawls 4.10, PDF + DOCX only
│   │   │   ├── chunker.py          # Text chunking
│   │   │   ├── embedder.py         # Cohere Embed API client
│   │   │   ├── retriever.py        # Weaviate hybrid search
│   │   │   ├── reranker.py         # Cohere Rerank API client
│   │   │   ├── synthesizer.py      # LLaMA synthesis + citation formatting
│   │   │   ├── query_router.py     # Rule-based query classifier
│   │   │   └── ajera_loader.py     # Ajera JSON singleton
│   │   └── schemas/
│   │       └── models.py
│   ├── config.yaml
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── pages/
│   │   │   └── SearchPage.tsx
│   │   └── components/
│   │       └── CitationCard.tsx
│   ├── package.json
│   └── Dockerfile
├── mock_corpus/                    # Local test docs, used until 4.10 access confirmed
├── docker-compose.yml
├── .env
├── .env.example
├── .gitignore
└── CLAUDE.md
```

---

## Setup

### Environment variables
Copy `.env.example` to `.env` and fill in:
```
COHERE_API_KEY=
WEAVIATE_HOST=localhost
WEAVIATE_PORT=8080
FILE_SERVER_PATH=/mnt/fileserver       # mounted 4.10 path, or /mock_corpus locally
LLAMA_MODEL_PATH=
AJERA_DATA_PATH=
FRONTEND_URL=http://192.168.3.11:5173
```

### Start all services
```bash
docker-compose up --build
```

### Start services (no rebuild)
```bash
docker-compose up
```

### Tear down
```bash
docker-compose down
```

### Tear down and wipe volumes (resets Weaviate index)
```bash
docker-compose down -v
```

---

## Development

### Backend only
```bash
source .venv/bin/activate
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend only
```bash
cd frontend
npm run dev
```

---

## API Endpoints
```
GET  /api/v1/health                          Server status
POST /api/v1/query                           RAG query → answer + citations + confidence
POST /api/v1/ingest                          Trigger ingestion run
GET  /api/v1/projects                        List indexed projects with chunk counts
GET  /api/v1/employees                       List employees (Ajera)
GET  /api/v1/employees/{id}/projects         Employee project history (Ajera)
```

---

## Retrieval Tuning
Key levers in `config.yaml`:

| Parameter | Default | Notes |
|---|---|---|
| Chunk size | TBD | Set after testing on mock corpus |
| Chunk overlap | TBD | Set after testing on mock corpus |
| top_k | 6 | Chunks passed to reranker |
| top_n (after rerank) | 3 | Chunks passed to LLM |
| Hybrid alpha | 0.5 | 0 = pure BM25, 1 = pure vector |

### Debug retrieval without LLM
```bash
# Once implemented
python scripts/debug_query.py --query "pipe burial depth" --project "project_id"
```

---

## Weaviate Schema
Collection: `ProjectChunk`

| Field | Type | Notes |
|---|---|---|
| chunk_text | text | Indexed for BM25 + vector |
| file_path | text | Full 4.10 path for citation link |
| page_number | int | For citation |
| chunk_id | text | Unique identifier |
| project_id | text | For filtering |
| department | text | From Ajera |
| file_type | text | pdf or docx |
| ingested_at | date | For staleness checks |

---

## Known Issues / Decisions Pending
- Chunking strategy not yet tuned — test on mock corpus before locking in
- Cohere keys not yet active — embedder mocks until `.env` is populated
- 4.10 mount not yet active — crawler uses `mock_corpus` until `FILE_SERVER_PATH` updated
- Chunk size / overlap TBD after mock corpus testing
- Multi-project aggregation queries (e.g. "all Vegas projects last 10 years") parked
  post-beta — Ajera metadata handles simple meta queries for now

---

## Beta Success Criteria
- Natural language queries return synthesized answers
- Every answer includes at least one clickable `file://` citation
- Citations open the correct source file in Chrome
- Personnel queries route correctly through Ajera
- No raw files stored on 3.11 under any circumstances
- Query response time under 5 seconds
- Retrieval works across varied query phrasing, not just curated queries