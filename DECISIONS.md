# Design Decisions & Rationale

This document captures key implementation choices made during MVP development.

## 1. PDF Text Extraction: pdfplumber

**Choice:** `pdfplumber` over `PyMuPDF` (fitz)

**Rationale:**
- Better handling of complex layouts (tables, multi-column)
- More accurate character-level bounding boxes
- Easier table extraction API for future enhancement
- Active maintenance and good documentation

**Trade-off:** Slightly slower than PyMuPDF on large files, but accuracy > speed for this use case.

## 2. Embedding Model: all-MiniLM-L6-v2

**Choice:** `sentence-transformers/all-MiniLM-L6-v2`

**Rationale:**
- 384-dimensional embeddings (good balance of quality vs size)
- Fast inference (~20ms per chunk on CPU)
- Well-suited for semantic search in technical documents
- Widely tested and reliable

**Alternative considered:** `all-mpnet-base-v2` (higher quality, 768-dim, but 2x slower)

**Decision:** Start with MiniLM; upgrade if search quality insufficient in evaluation.

## 3. Chunking Strategy: Semantic-First with Fallback

**Choice:** Hybrid approach:
1. Detect headings/sections (regex-based)
2. Split at semantic boundaries (headings)
3. Fallback to fixed 500-token windows if no headings detected

**Rationale:**
- Engineering documents often have clear structure (sections, specs)
- Semantic chunks improve citation relevance
- Fallback ensures all documents are chunked even if unstructured

**Parameters:**
- 500 tokens per chunk (balances context vs retrieval precision)
- 100 token overlap (prevents boundary splitting of key facts)

## 4. LLM Integration: llama-cpp-python

**Choice:** `llama-cpp-python` bindings over alternatives (vLLM, transformers)

**Rationale:**
- Optimized for GGUF quantized models on consumer GPUs
- Lower memory footprint (Q6_K quantization)
- Faster cold-start than full PyTorch
- Good CPU fallback if GPU unavailable

**Model:** Llama-3.2-3B-Instruct (Q6_K quantized)
- Small enough for RTX 4090 with room for embeddings
- Instruction-tuned for QA tasks
- Quantization preserves quality while enabling fast inference

## 5. Vector DB: ChromaDB

**Choice:** ChromaDB with persistent storage

**Rationale:**
- Embedded (no separate server process needed)
- Simple API for upsert/query
- Built-in HNSW indexing for fast approximate search
- Good Python integration
- Local-first (meets security requirement)

**Alternative considered:** Qdrant (more features but overkill for MVP)

## 6. OCR: Tesseract

**Choice:** Tesseract OCR (via pytesseract)

**Rationale:**
- Open-source, widely available
- Good accuracy on printed text
- Easy installation (`apt install`)
- Configurable language packs

**Future enhancement:** Consider PaddleOCR for handwritten text or complex layouts.

## 7. Prompt Engineering: Strict JSON Output

**Choice:** Force LLM to output JSON only, with schema provided in system prompt

**Rationale:**
- Enables validation via Pydantic
- Prevents hallucination of unstructured text
- Easier to parse and test
- Clear separation of concerns (LLM generates, backend validates)

**Implementation:**
- `extract_prompt.txt`: Structured fact extraction
- `qa_prompt.txt`: QA with mandatory citations

## 8. Citation Format: Provenance Triple

**Choice:** Every citation includes `(file_path, page, chunk_id)`

**Rationale:**
- File path: user can locate source document
- Page: enables PDF viewer navigation
- Chunk ID: deterministic, enables debugging and audit

**Extension:** Include `bbox` (bounding box) when available for text highlighting.

## 9. API Design: RESTful with Pydantic Validation

**Choice:** FastAPI with Pydantic schemas

**Rationale:**
- Auto-generated OpenAPI docs (`/docs`)
- Strong typing and validation
- Async support for future scaling
- Easy to test with `TestClient`

**Endpoints:**
- `POST /api/v1/projects/{project_id}/upload` → file upload
- `POST /api/v1/projects/{project_id}/ingest` → trigger pipeline
- `POST /api/v1/query` → QA endpoint
- `GET /api/v1/health` → system status

## 10. Frontend: React + Vite

**Choice:** React with TypeScript, Vite build tool

**Rationale:**
- Fast dev server (HMR)
- TypeScript for type safety
- Modern tooling (ES modules, tree-shaking)
- Easy PDF viewer integration (react-pdf)

**Components:**
- `SearchPage.tsx`: Query input + results + citations
- `UploadPage.tsx`: File upload interface
- `ResultCard.tsx`: Display answer + citations

## 11. Testing Strategy: Unit + Integration

**Choice:** pytest for backend, vitest for frontend

**Tests:**
- Unit: extractors, chunker, embedder, indexer (isolated)
- Integration: full query endpoint (extract → chunk → embed → index → query)
- Smoke: health check, stub mode validation

**Coverage target:** 70%+ for core modules

## 12. Docker: GPU-Aware Compose

**Choice:** Docker Compose with NVIDIA runtime

**Rationale:**
- Reproducible environment
- GPU passthrough for CUDA (RTX 4090)
- Volumes for data persistence
- Easy multi-service orchestration (backend, frontend, optional Chroma server)

**Note:** Requires NVIDIA Container Toolkit on host.

## 13. Logging: Security-First

**Choice:** Log minimal metadata, never raw document text

**Rationale:**
- Privacy: documents may contain sensitive engineering data
- Compliance: GDPR/data retention considerations
- Debugging: log chunk IDs, not content

**Logs:**
- `queries.log`: timestamp, project_id, query, top_chunk_ids, elapsed_ms
- `ingest_report.json`: file counts, errors
- `errors.log`: exceptions with stack traces

## 14. Stub Mode: Graceful Degradation

**Choice:** If LLM model file absent, run in deterministic stub mode

**Rationale:**
- Enables testing without downloading large model
- CI/CD friendly
- Clear indication to user (`stub_mode: true` in logs)

**Stub response:** "Not found in indexed documents" with empty citations.

## 15. Normalization: Date and Unit Handling

**Choice:** Normalize dates to ISO 8601, units to metric + imperial

**Rationale:**
- Engineering docs mix date formats (MM/DD/YYYY, DD-MMM-YY)
- Units often mixed (feet, meters, inches)
- Normalization enables semantic search and comparison

**Implementation:**
- Regex-based detection
- Store both original and normalized values in chunk metadata

## Future Improvements (Post-MVP)

1. **Table extraction:** Integrate `camelot-py` or `tabula-py` for structured table parsing
2. **Hybrid search:** Combine semantic (Chroma) + keyword (Elasticsearch)
3. **Reranker:** Add cross-encoder reranking for top-K results
4. **Multi-modal:** Use vision models (CLIP, LLaVA) for diagram understanding
5. **Human-in-the-loop:** Validation UI for extracted facts
6. **Cloud LLM pilot:** Compare GPT-4 accuracy/cost on 100-query eval set

---

**Document Version:** v0.1.0  
**Last Updated:** 2025-11-14  
**Author:** GitHub Copilot (for Peter)
