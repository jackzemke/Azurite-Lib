# AI Coding Agent Instructions

## Mission: 2/18 Pilot Stabilization

**Priority:** Make AAA reliable for non-technical users. Retrieval quality > new features.

**Success Criteria:** A skeptical pilot user says "It actually helped me find something faster than digging through folders."

## Architecture

**Stack:** FastAPI + React/Vite + ChromaDB (embedded) + Llama-3.2-3B-Instruct (Q6_K) + all-MiniLM-L6-v2

**Data Flow:**
```
Ingestion: Upload → pdfplumber/docx extract → EnhancedChunker → Embedder → ChromaDB
Query:     Embed → QueryExpander → Filter(employee) → Retrieve top-K → Diversity filter → LLM → JSON+citations
```

## Critical Patterns

### 1. Retrieval Pipeline (Highest Priority Area)
Current issues: inconsistent results, duplicate citations, requires "perfect" queries.

**Key components to modify:**
- `app/backend/app/core/indexer.py` — `query()` method, diversity filtering (`_apply_diversity`), doc type boosting
- `app/backend/app/core/query_expander.py` — synonym expansion, query rewriting, `get_doc_type_hints()`
- `app/backend/app/core/enhanced_chunker.py` — chunk boundaries, context preservation
- `app/backend/config.yaml` — `chunk_size_tokens: 500`, `chunk_overlap_tokens: 100`, `top_k: 6`

**Debugging retrieval:**
```bash
python app/scripts/debug_query.py --query "pipe diameter" --project demo_project
# Shows: embedding, distances, retrieved chunks WITHOUT LLM
```

### 2. Failure Isolation
When output is bad, identify: Chunking? Retrieval? Prompt? Generation?

**Logging tags in `query.py`:**
```python
logger.info(f"[RETRIEVAL] Query: '...' | Scope: ... | Results: {len(chunks)}")
logger.info(f"[RETRIEVAL] Top chunks: [1] d=0.35 filename; [2] d=0.42 ...")
# Log chunk_ids and distances, NOT chunk text (privacy)
```

**Debug scripts:**
- `app/scripts/debug_query.py` — bypasses LLM, shows raw retrieval
- `app/scripts/debug_chromadb.py` — inspect index contents
- `app/scripts/validate_e2e.py` — full pipeline health check

### 3. Stub Mode
System runs without 5GB model. Check `llm_client.stub_mode` in all responses:
```python
response = QueryResponse(..., stub_mode=llm_client.stub_mode)
```

### 4. Citation Provenance — NEVER omit
Every answer needs `citations: [{project_id, file_path, page, chunk_id}]`. Empty array + `confidence: "low"` if nothing found.

### 5. Security Logging
**Metadata only.** See `_log_query()` in `query.py`:
```python
# ✅ chunk_id, project_id, query, elapsed_ms, confidence
# ❌ NEVER: chunk text, file contents
```

### 6. Ingestion Pipeline
**Sync endpoint:** `POST /api/v1/projects/{project_id}/ingest` — blocks until complete
**Async endpoint:** `POST /api/v1/projects/{project_id}/ingest/async` — returns job_id (requires Redis)

**Key files:**
- `app/backend/app/api/ingest_v2.py` — enhanced ingestion with validation
- `app/backend/app/core/job_queue.py` — async job infrastructure (Redis Queue)
- `app/backend/app/core/ingest_worker.py` — background processing logic

**Performance notes:**
- Large uploads: Use async endpoint, poll `/api/v1/jobs/{job_id}` for status
- Bottlenecks: PDF extraction (pdfplumber), embedding generation
- No Redis: Falls back to synchronous processing

### 7. Concurrency (Future Focus)
CPU fallback under concurrent load causes severe latency. For pilot (single-user), acceptable.
For wider deployment, consider: request queuing, GPU batching, or cloud inference.

## Developer Commands

```bash
# Backend (port 8000)
source .venv/bin/activate && cd app/backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Frontend (port 5173)
cd app/frontend && npm run dev

# Tests
pytest -v
pytest tests/test_retrieval_quality.py -v  # Vague query tests
pytest tests/test_query_endpoint.py -v     # Integration tests

# Debug tools
python app/scripts/debug_query.py --query "..." --project demo_project
python app/scripts/validate_e2e.py
python app/scripts/debug_chromadb.py
```

## Key Files

| Area | File |
|------|------|
| **RAG pipeline** | `app/backend/app/api/query.py` |
| **Retrieval + diversity** | `app/backend/app/core/indexer.py` |
| **Query rewriting** | `app/backend/app/core/query_expander.py` |
| **Chunking** | `app/backend/app/core/enhanced_chunker.py` |
| **Embeddings** | `app/backend/app/core/embedder.py` |
| **LLM + stub mode** | `app/backend/app/core/llm_client.py` |
| **QA prompt** | `app/backend/app/prompts/qa_prompt.txt` |
| **Config** | `app/backend/config.yaml` |
| **Retrieval tests** | `tests/test_retrieval_quality.py` |

## Retrieval Improvement Levers

| Lever | Current | Notes |
|-------|---------|-------|
| Chunk size | 500 tokens | Try 300-800 |
| Overlap | 100 tokens | Try 50-150 |
| top_k | 6 | Try 10 with stricter re-rank |
| Diversity | max 2/doc + family dedup | Prevents invoice flooding |
| Doc type boost | 0.05 distance reduction | Boosts contracts for "client" queries |
| Query expansion | 3 synonyms per keyword | See `EXPANSION_RULES` |

## Test Cases for Vague Queries

These must pass (`tests/test_retrieval_quality.py`):
- `"who was the client"` → returns results with distance < 0.6, contract in top 2
- `"summary"` → returns results with distance < 0.5
- `"what is this project about"` → returns results with distance < 0.5
- `"environmental site assessment"` → technical query, distance < 0.45
- Diversity: max 2 chunks per file, max 4 chunks from same doc family (e.g., invoices)

## Acceptance Criteria

- [x] Vague queries ("what's this project about") return relevant results
- [x] No duplicate citations from same file in single response
- [x] Sibling documents (multiple invoices) deduplicated
- [ ] Graceful "I couldn't find that" instead of hallucination
- [x] Citations always present (or empty + low confidence)
- [x] Works in stub mode (CI/CD)
- [x] No raw text in logs
- [x] Retrieval quality tests pass
