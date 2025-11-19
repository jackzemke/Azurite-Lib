# Ingestion Checklist

This checklist ensures correct document ingestion and indexing for each project.

## Pre-Ingestion

- [ ] **Documents collected**: All project files in `/data/raw_docs/{project_id}/`
- [ ] **File formats verified**: PDF, DOCX, XLSX, images (PNG, JPG, TIFF)
- [ ] **Tesseract installed**: Run `tesseract --version` to confirm OCR available
- [ ] **Model file present**: Check `/data/models/Llama-3.2-3B-Instruct-Q6_K.gguf` exists (or stub mode enabled)
- [ ] **Backend running**: Health check passes (`GET /api/v1/health`)

## Ingestion Steps

### 1. Upload Documents

**Method A: API**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/projects/{project_id}/upload \
  -F "files=@document1.pdf" \
  -F "files=@document2.docx"
```

**Method B: Frontend**
- Navigate to Upload page
- Select project ID
- Drag-and-drop or select files

**Verify:**
- [ ] Files appear in `/data/raw_docs/{project_id}/`
- [ ] Upload response JSON includes all filenames

### 2. Trigger Ingestion

**Method A: API**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/projects/{project_id}/ingest \
  -H "Content-Type: application/json"
```

**Method B: CLI**
```bash
python app/scripts/ingest_cli.py --project {project_id}
```

**Expected Duration:**
- Small project (5-10 files): 30-60 seconds
- Medium project (50 files): 5-10 minutes
- Large project (200+ files): 20-30 minutes

### 3. Verify Ingestion

Check ingestion report:
```bash
cat /data/logs/ingest_report_{project_id}.json
```

**Expected fields:**
```json
{
  "project_id": "proj_demo",
  "files_processed": 10,
  "chunks_created": 342,
  "errors": [],
  "duration_seconds": 47.2,
  "timestamp": "2025-11-14T12:00:00Z"
}
```

- [ ] `files_processed` matches uploaded file count
- [ ] `chunks_created` > 0 (typical: 20-50 chunks per document)
- [ ] `errors` array is empty (or contains only minor warnings)

### 4. Verify Chunks Created

Check chunk directory:
```bash
ls -l /data/chunks/{project_id}/
```

**Expected:**
- One subdirectory or JSON file per source document
- Chunk filenames: `{file_basename}__chunk_{n}.json`

Sample a chunk:
```bash
cat /data/chunks/{project_id}/document1.pdf__chunk_0001.json | jq .
```

**Verify fields:**
- [ ] `chunk_id` present and unique
- [ ] `project_id` matches
- [ ] `file_path` correct
- [ ] `text` field non-empty (50+ characters typical)
- [ ] `page_number` present (for PDFs/DOCX)
- [ ] `tokens` count reasonable (400-600 for 500-token target)

### 5. Verify Embeddings Created

Check embeddings file:
```bash
ls -l /data/embeddings/{project_id}.parquet
```

**Verify:**
- [ ] File exists and size > 0
- [ ] File size roughly: `chunks_created * 384 * 4 bytes` (for MiniLM-L6-v2)

Optional: Inspect parquet:
```python
import pandas as pd
df = pd.read_parquet('/data/embeddings/{project_id}.parquet')
print(df.head())
print(df['embedding_vector'].iloc[0].shape)  # Should be (384,)
```

### 6. Verify Chroma Index

Check Chroma DB:
```bash
ls -l /data/index/chroma/
```

**Verify:**
- [ ] Directory exists
- [ ] Contains SQLite DB and data files
- [ ] Size > 0

Query health endpoint:
```bash
curl http://127.0.0.1:8000/api/v1/health | jq .
```

**Verify:**
- [ ] `chroma_indexed_projects` includes `{project_id}`

### 7. Test Query

Run a simple query:
```bash
curl -X POST http://127.0.0.1:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"project_id":"{project_id}","query":"What is this project about?","k":3}' | jq .
```

**Verify:**
- [ ] `answer` field present (not empty or generic error)
- [ ] `citations` array has 1+ items
- [ ] Citation `file_path` matches a source document
- [ ] `confidence` field is `high`, `medium`, or `low`

## Troubleshooting

### Issue: `files_processed: 0`

**Possible causes:**
1. No files in `/data/raw_docs/{project_id}/`
2. Permission issue (backend can't read directory)
3. Extractor crash (check `errors.log`)

**Fix:**
```bash
# Check directory
ls /data/raw_docs/{project_id}/

# Check permissions
chmod -R 755 /data/raw_docs/{project_id}/

# Check error log
tail -50 /data/logs/errors.log
```

### Issue: OCR Failing

**Symptoms:** `errors` array contains "Tesseract not found" or "OCR failed"

**Fix:**
```bash
# Install Tesseract
sudo apt update
sudo apt install tesseract-ocr tesseract-ocr-eng

# Verify
tesseract --version
```

### Issue: GPU Out of Memory

**Symptoms:** Backend crashes during embedding or LLM inference with CUDA OOM error

**Fix:**
Edit `config.yaml`:
```yaml
model:
  n_gpu_layers: 20  # Reduce from 40
  
embedding:
  batch_size: 16  # Reduce from 32
```

Or run in CPU mode:
```yaml
model:
  n_gpu_layers: 0  # CPU only
```

### Issue: Chunks Created but No Embeddings

**Possible causes:**
1. Embedding model download failed (sentence-transformers)
2. Out of memory during embedding

**Fix:**
```bash
# Re-download embedding model
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Check available RAM
free -h

# Reduce batch size in config.yaml
```

### Issue: Query Returns "Not found in indexed documents"

**Possible causes:**
1. Chroma index empty or corrupted
2. Query semantically unrelated to indexed content
3. Similarity threshold too high

**Debugging:**
```bash
# Check Chroma index count
python -c "
import chromadb
client = chromadb.PersistentClient(path='/data/index/chroma')
collection = client.get_or_create_collection('project_docs')
print('Total chunks:', collection.count())
"

# Try a very broad query
curl -X POST http://127.0.0.1:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"project_id":"{project_id}","query":"project","k":10}'
```

**Fix:**
Lower similarity threshold in `config.yaml`:
```yaml
index:
  similarity_threshold: 0.3  # Down from 0.5
```

## Post-Ingestion Validation

Run evaluation script:
```bash
python evaluation/eval_metrics.py --project {project_id}
```

This compares API responses to ground truth queries (if available).

**Target metrics:**
- Citation accuracy: ≥75% (85% ideal)
- QA accuracy: ≥70%
- Mean query latency: <500ms

## Sign-Off

Project: `__________________`  
Ingestion Date: `__________________`  
Files Ingested: `__________________`  
Chunks Created: `__________________`  
Verified By: `__________________`  

Notes:
```
_________________________________________________
_________________________________________________
_________________________________________________
```

---

**Document Version:** v0.1.0  
**Last Updated:** 2025-11-14
