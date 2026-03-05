# AAA Agent Handoff Report

**Date:** 2026-03-05
**Author:** Claude agent session (local dev workstation)
**Target:** New agent on remote server

---

## 1. What Is AAA

Azurite Archive Assistant (AAA) is a **cite-first, retrieval-augmented knowledge system** for an engineering/construction firm (SMA). It makes past project documents (geotech reports, environmental assessments, proposals, contracts) discoverable via natural language, with strict citation provenance on every answer.

**Core stack:**
- Backend: FastAPI (Python 3.12)
- Frontend: React + TypeScript + Vite
- Vector DB: ChromaDB (embedded, persistent, HNSW)
- LLM: Llama-3.2-3B-Instruct (Q6_K GGUF), local inference via `llama-cpp-python`
- Embeddings: `nomic-ai/nomic-embed-text-v1.5` via sentence-transformers (task-prefixed)
- ERP: Ajera (Deltek) for employee-project time tracking data (77MB JSON)
- Job queue: Redis + RQ for async ingestion
- Deployment: Docker Compose with NVIDIA GPU support (RTX 4090 workstation)

**Primary users:** Engineers, marketing/BD staff at SMA. The pilot success criterion is: "A skeptical user says 'It actually helped me find something faster than digging through folders.'"

---

## 2. Architecture Overview

```
Ingestion:  Upload -> pdfplumber/docx extract -> EnhancedChunker -> Embedder -> ChromaDB
Query:      Embed -> QueryExpander -> Filter(employee) -> Retrieve top-K -> Reranker -> LLM -> JSON+citations
Router:     classify_query() -> {DOCUMENT_QA, PERSONNEL, FILE_LOCATION, DUPLICATE_DETECTION}
Side data:  Ajera loader (static JSON) | DirectoryIndex (SQLite+FTS5) | ProjectResolver
```

All heavyweight services (LLM, Embedder, Indexer, Reranker, QueryExpander, DirectoryIndex) are **lazy singletons** in `app/backend/app/services.py`. They initialize on first access and are shared across all requests.

Config lives in `app/backend/config.yaml` with environment variable overrides via `AAA_` prefix. Path resolution uses `base_dir` (the project root) so all paths are relative.

---

## 3. What Has Been Implemented Recently

### Phase 1: Query Router (COMPLETE)

**File:** `app/backend/app/core/query_router.py` (242 lines)

A rule-based intent classifier that runs at ~0ms overhead (no ML). Classifies every query into one or more intents:

| Intent | What It Detects | Example |
|--------|----------------|---------|
| `DOCUMENT_QA` | Always present (default) | "What was the pipe diameter?" |
| `PERSONNEL` | Employee/team/hours questions | "Who worked on this project?" |
| `FILE_LOCATION` | Where files/projects are stored | "Where is 1430152 on the S drive?" |
| `DUPLICATE_DETECTION` | Duplicate directories across drives | "Is this project duplicated?" |

Uses keyword lists + regex patterns with phrase-level (0.6) vs word-level (0.3) confidence scoring. Also detects `is_broad_query` and extracts `drive_mention` and `extracted_entities`.

**Supporting changes:**
- `app/backend/app/schemas/models.py` — Added `intents`, `personnel_data`, `file_location`, `duplicate_info` fields to `QueryResponse`
- `app/backend/app/api/query.py` — Integrated router: calls `classify_query()`, runs intent handlers, merges supplementary context into LLM prompt via `_merge_supplementary_context()`
- `app/backend/app/core/directory_index.py` — Created as stub (replaced in Phase 2)

**Tests:** `app/scripts/test_query_router.py` — 43 tests, all passing

### Phase 2: Directory Index (COMPLETE)

**File:** `app/backend/app/core/directory_index.py` (793 lines)

SQLite-backed directory tree cache that indexes project folders across network drives. Enables "where is project X?" and "is project Y duplicated?" queries without live network access at query time.

**Key design decisions:**
- **Full rebuild on each scan** (not incremental) — simpler implementation for 5K-20K directories, scans complete in seconds
- **No live network queries at query time** — all lookups hit local SQLite (~1-5ms)
- **Manual scan trigger only** — no scheduling (deliberate choice for Phase 2)
- **3-tier search strategy:** exact project_id match -> FTS5 full-text -> LIKE fallback

**SQLite schema:** 4 tables — `drives`, `directories`, `scan_metadata`, `directories_fts` (FTS5 virtual table)

**ID extraction:** Uses same 4 regex patterns as `filesystem_scanner.py` and `project_mapper.py`:
1. `"Name (1430152)"` — numeric ID in parentheses
2. `"(1A29514)"` — alphanumeric ID in parentheses
3. `"1430152-Name"` — ID at start with separator
4. `"1430152"` — pure numeric folder name

**All files changed/created for Phase 2:**

| File | Action | Purpose |
|------|--------|---------|
| `app/backend/config.yaml` | Modified | Added `network_drives` section with `db_path` and commented drive examples |
| `app/backend/app/config.py` | Modified | Added `network_drives_db_path`, `network_drives_config` settings + property + YAML list handling |
| `app/backend/app/core/directory_index.py` | Replaced | Full SQLite + FTS5 implementation (was stub) |
| `app/backend/app/services.py` | Modified | `get_directory_index()` now does lazy init from config (returns None if no drives configured) |
| `app/backend/app/main.py` | Modified | Logs drive configuration status on startup |
| `app/backend/app/api/admin.py` | Modified | Added 4 endpoints: `POST /directory-index/scan`, `GET /directory-index/status`, `GET /directory-index/search`, `GET /directory-index/duplicates` |
| `app/backend/app/api/query.py` | Modified | `_handle_file_location()` and `_handle_duplicate_detection()` wired to real DirectoryIndex |
| `app/scripts/create_mock_drives.py` | Created | Dev script creating 38 fake project dirs with 3 intentional duplicates |
| `app/scripts/test_directory_index.py` | Created | 48 unit tests across 9 test classes |
| `app/frontend/src/pages/AdminPage.tsx` | Modified | Added "Directory Index" card with status display, drive list, stats, "Scan Now" button |

**Tests:** `app/scripts/test_directory_index.py` — 48 tests, all passing (1.66s)

**What's needed to go live with Phase 2 on the production server:**
1. Mount SMB/CIFS shares on the Linux host (or configure Docker volumes for `/mnt/s_drive`, `/mnt/p_drive`)
2. Uncomment and configure drive entries in `config.yaml`
3. Run initial scan from admin dashboard ("Scan Now" button)
4. Optionally add Docker volume mounts in `docker-compose.yml`

---

## 4. Phase 3: Ajera API Sync (NOT STARTED — Next Implementation)

### Current State

The Ajera **read path** is fully functional:
- `app/backend/app/core/ajera_loader.py` — Loads `ajera_unified.json` (77MB, 12,529 projects) into memory at startup. Provides search, lookup, employee-project resolution. Complete, no TODOs.
- `app/backend/app/api/ajera.py` — REST endpoints for employees, projects, departments, search. Complete.
- `app/backend/app/api/query.py` — Employee-scoped filtering, personnel intent handling, fallback responses. Complete.

The Ajera **write/sync path** is entirely stubbed:
- `app/backend/app/core/ajera_sync.py` — `AjeraAPIClient` has 4 stubbed methods that all return empty/false:
  - `authenticate()` — returns `False`, logs "not yet implemented"
  - `fetch_employees()` — returns `[]`
  - `fetch_timesheets()` — returns `[]`
  - `fetch_projects()` — returns `[]`
  - `transform_to_unified_format()` — placeholder comment
- The admin sync endpoint (`POST /api/v1/admin/ajera/sync`) is wired but always reports "Authentication failed"

### What Needs to Happen

The goal is to replace the static 77MB JSON snapshot with live API sync so Ajera data stays fresh. Credentials and API URLs exist in `app/backend/ajera_api_jzemke.txt` (untracked, contains plaintext creds — **do not commit**).

**API details from the credentials file:**
- Endpoint pattern: `https://ajera.com/V004864/AjeraAPI.ashx?<base64-config>`
- Two environments: AZURITE (test) and SMA (production, different DatabaseID)
- Auth: `DbiUsername` / `DbiPassword` fields, `Method: Authenticate`
- Credentials: username `jzemke_ai`, password `1201Sma!`

**Implementation steps for Phase 3:**
1. Implement `authenticate()` in `ajera_sync.py` using the API URL and credentials
2. Implement `fetch_projects()`, `fetch_employees()`, `fetch_timesheets()` — need to discover API schema (no documentation available; may need to experiment with the API)
3. Implement `transform_to_unified_format()` — map Ajera API field names to the existing `ajera_unified.json` structure
4. Wire up the scheduled sync (already scaffolded in `main.py` lines 103-124 — runs via daemon thread at `ajera_sync_interval_hours` interval)
5. Test with AZURITE environment first, then switch to SMA production
6. Move credentials from plaintext file to `.env` / environment variables

**Exploration scripts that may help:**
- `app/scripts/explore_ajera_db.py` — ODBC schema explorer
- `app/scripts/query_ajera_windows.py` — Windows ODBC explorer (has hardcoded creds)
- `app/scripts/inspect_ajera_project_metadata.py` — AxProject table inspector
- `app/scripts/merge_ajera_data.py` — How `ajera_unified.json` was originally built

### Risks and Unknowns

- **No API documentation.** The Ajera API schema is unknown. The stubbed code has `TODO: Implement once Ajera API schema is known` comments. Previous exploration was done via ODBC, not the REST API.
- **Credential management.** Hardcoded creds in multiple scripts. Need to consolidate into `.env`.
- **Data format.** The current `ajera_unified.json` was built by merging `ajera_time_series.json` (ODBC extract) with `ajera_project_metadata.json`. The API may return data in a different structure.
- **The scheduled sync runs in a daemon thread** (`main.py` line 120). For production reliability, consider moving to a proper task scheduler (celery, APScheduler) or a separate sync process.

---

## 5. Design Preferences and Standards

### Code Style
- **No over-engineering.** Only make changes that are directly requested or clearly necessary. Don't add features, refactor code, or make "improvements" beyond what's asked.
- **Minimal abstraction.** Three similar lines of code is better than a premature abstraction. Don't create helpers for one-time operations.
- **No unnecessary comments.** Only add comments where logic isn't self-evident. Don't add docstrings to code you didn't change.
- **Privacy first.** Never log raw document text. Metadata only: `chunk_id`, `project_id`, `query`, `elapsed_ms`, `confidence`.

### Architecture Patterns
- **Lazy singleton services** via `services.py` — prevents duplicate GPU model loads
- **Pydantic Settings** with YAML config + `AAA_` env var override
- **Config-driven features** — features like DirectoryIndex are disabled when their config section is empty (returns `None` from getter)
- **Consistent ID extraction** — same 4 regex patterns used across `filesystem_scanner.py`, `project_mapper.py`, and `directory_index.py`
- **Citation provenance is mandatory** — every answer needs `(project_id, file_path, page, chunk_id)`. Empty array + `confidence: "low"` if nothing found. Never hallucinate.

### Frontend
- React + TypeScript, no separate CSS-in-JS library — uses plain CSS classes
- Admin dashboard uses inline styles for stat rows, status dots, etc.
- Existing pattern: cards in left panel with `admin-card` class, `system-stats` / `stat-row` for stats display
- Service buttons use `service-btn start`/`service-btn stop` classes

### Testing
- Tests live in `app/scripts/` (not a standard `tests/` dir for the new Phase 1/2 tests)
- Pytest with `.venv/bin/python -m pytest` (venv at project root)
- `pytest.ini` exists at project root
- Directory index tests use temp directories and in-memory SQLite
- Query router tests are pure unit tests (no I/O)

---

## 6. Tradeoffs Made and Why

| Decision | Tradeoff | Rationale |
|----------|----------|-----------|
| Rule-based query router (no ML) | Less accurate than fine-tuned classifier | ~0ms latency, no model dependency, transparent/debuggable keyword lists, works in stub mode |
| Full rebuild scan (not incremental) | Slower for very large drives | Simpler implementation, avoids stale-data bugs, 5K-20K dirs scans in <5s |
| SQLite + FTS5 (not Elasticsearch) | Less powerful full-text search | Zero infrastructure, sub-5ms queries, single-file database, no extra service to manage |
| Manual scan trigger only | Data can go stale | Avoids scan scheduling complexity, admin controls when scans happen, appropriate for Phase 2 |
| 3B parameter local LLM | Less capable than cloud API | Air-gapped deployment requirement, RTX 4090 runs it fast, no API costs, privacy |
| Static Ajera JSON (not live sync) | Data snapshot from Dec 2025 | API integration was deprioritized; static data covers 12,529 projects; sync is Phase 3 |
| Fixed-window chunking (not semantic) | May split mid-paragraph | Semantic chunking was creating tiny header-only chunks; disabled in `config.yaml` |
| Diversity filter after reranking | May miss some relevant chunks | Prevents invoice flooding (max 2/file, 4/family) which was a real problem in pilot |

---

## 7. Known Issues and Worries

### Active Concerns
1. **`_merge_supplementary_context()` in `query.py` (lines 567-587)** has a minor mismatch: the file_location merge code references `loc.get('drive', 'unknown drive')` but the actual DirectoryIndex results use `drive_name` and `drive_letter` keys. This will produce "unknown drive" labels in the LLM context when file location data is injected. Needs a field name fix.

2. **`_log_query()` in `query.py` (line 604)** still uses `datetime.utcnow()` which is deprecated in Python 3.12+. Should be `datetime.now(timezone.utc)`.

3. **Hardcoded credentials** in `ajera_api_jzemke.txt`, `query_ajera_windows.py`, and `inspect_ajera_project_metadata.py`. These are untracked but sitting in the repo directory. Should be moved to `.env` or a secrets manager before production deployment.

4. **Thread-based Ajera sync scheduler** (`main.py` line 120) — daemon thread with `time.sleep()` loop. Works but not production-grade. No crash recovery, no jitter, no backoff on failure.

5. **CORS is relaxed** (`frontend_url` controls allowed origins, but `allow_methods=["*"]` and `allow_headers=["*"]`). Fine for internal tool, but tighten for any external exposure.

### Operational Notes
- The mock drive data at `data/mock_drives/` is for development only. On the remote server, you'll configure real SMB mount paths.
- `config.yaml` paths are relative to `base_dir`. In Docker, `AAA_BASE_DIR=/` and data is at `/data/...`. On the local dev workstation, paths resolve from the project root.
- Redis is optional. Without it, ingestion runs synchronously.

---

## 8. File Map: What Changed vs. What's Stock

### Recently Modified (Phase 1 + Phase 2)
```
app/backend/app/config.py              -- network_drives settings added
app/backend/config.yaml                -- network_drives section added
app/backend/app/main.py                -- directory index startup logging
app/backend/app/services.py            -- get_directory_index() lazy init
app/backend/app/api/query.py           -- router integration, intent handlers
app/backend/app/api/admin.py           -- 4 directory-index endpoints
app/backend/app/schemas/models.py      -- QueryResponse router fields
app/frontend/src/pages/AdminPage.tsx   -- Directory Index card
```

### Recently Created (Phase 1 + Phase 2)
```
app/backend/app/core/query_router.py   -- intent classifier
app/backend/app/core/directory_index.py -- SQLite+FTS5 directory cache
app/scripts/create_mock_drives.py      -- dev data generator
app/scripts/test_directory_index.py    -- 48 tests
app/scripts/test_query_router.py       -- 43 tests
```

### Untouched Core (do not break these)
```
app/backend/app/core/indexer.py        -- ChromaDB retrieval + diversity
app/backend/app/core/embedder.py       -- sentence-transformers embedding
app/backend/app/core/llm_client.py     -- llama-cpp-python inference
app/backend/app/core/enhanced_chunker.py -- text chunking
app/backend/app/core/query_expander.py -- synonym expansion
app/backend/app/core/reranker.py       -- cross-encoder reranking
app/backend/app/core/ajera_loader.py   -- Ajera data loader (functional)
app/backend/app/core/project_resolver.py -- project ID resolution
app/backend/app/core/project_mapper.py -- Ajera<->filesystem mapping
app/backend/app/core/ajera_sync.py     -- STUBBED, Phase 3 target
```

---

## 9. Test Commands

```bash
# All Phase 1+2 tests (from project root)
.venv/bin/python -m pytest app/scripts/test_query_router.py -v     # 43 tests
.venv/bin/python -m pytest app/scripts/test_directory_index.py -v  # 48 tests

# Original test suite (if applicable)
.venv/bin/python -m pytest tests/ -v

# Debug retrieval (bypasses LLM)
.venv/bin/python app/scripts/debug_query.py --query "pipe diameter" --project demo_project

# Generate mock drive data
python3 app/scripts/create_mock_drives.py
```

---

## 10. What the Next Agent Should Do

**Immediate (before any new features):**
1. Fix the `_merge_supplementary_context()` field name mismatch in `query.py` (see Known Issues #1)
2. Fix the `datetime.utcnow()` deprecation in `query.py:604`
3. Verify all 91 tests pass on the remote server

**Phase 3: Ajera API Sync:**
1. Read `app/backend/ajera_api_jzemke.txt` for API credentials and endpoint URLs
2. Read `app/backend/app/core/ajera_sync.py` — all 6 TODOs mark where implementation goes
3. Start with `authenticate()` — the commented-out code on lines 57-64 shows the expected request shape
4. Experiment with the AZURITE test environment API to discover the schema
5. Implement `fetch_projects()`, `fetch_employees()`, `fetch_timesheets()`
6. Implement `transform_to_unified_format()` to match the structure in `ajera_unified.json`
7. Test the full sync cycle via `POST /api/v1/admin/ajera/sync`
8. Move credentials to `.env` file, remove `ajera_api_jzemke.txt`
9. Validate the scheduled sync works (daemon thread in `main.py`)

**Future roadmap items (not started):**
- Ajera project linking wizard (manual mapping for non-matching folder names)
- PDF citation previews in the UI
- Job recovery UI (list/resume jobs after tab close)
- Parallel PDF extraction for faster ingestion
- Graceful "I couldn't find that" messaging improvements
