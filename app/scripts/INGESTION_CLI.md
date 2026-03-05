# CLI Ingestion Tools

Tools for ingesting documents from the command line without using the web UI.

## Quick Start

### Option 1: Simple Bash Script (Recommended for Background Work)

Use the containers with lower priority so you can work on other projects:

```bash
# 1. Reduce worker priority so it doesn't hog CPU/GPU
docker update --cpus="2" aaa-worker   # Limit to 2 CPU cores
docker exec aaa-worker renice -n 19 -p 1  # Lower priority

# 2. Trigger ingestion (replace with your project folder name)
./app/scripts/ingest.sh "My Project (1234567)"

# 3. Or run multiple projects in background
for project in "Project A" "Project B" "Project C"; do
  ./app/scripts/ingest.sh "$project" &
done
wait
```

### Option 2: Standalone Python Script (No API Needed)

For when you want maximum control or don't want the worker running:

```bash
# Stop the worker so it doesn't use resources
docker stop aaa-worker

# Run ingestion directly with low priority
# (Requires Python virtualenv with dependencies)
cd /path/to/project-library
source venv/bin/activate  # Your virtualenv
nice -n 19 ionice -c 3 python app/scripts/ingest_standalone.py --project "My Project"
```

## Detailed Usage

### Bash Script (`ingest.sh`)

The bash script triggers async ingestion via the API and monitors progress.

**Pros:**
- Simple one-liner
- No Python environment needed (uses Docker)
- Shows real-time progress
- Can run multiple in parallel

**Cons:**
- Requires worker container running
- Worker will use GPU (but you can limit its priority)

**Usage:**
```bash
# Basic usage
./app/scripts/ingest.sh "Project Name (123456)"

# Run in background (fire and forget)
nohup ./app/scripts/ingest.sh "Project Name" > ingest.log 2>&1 &

# Check progress later
curl http://localhost:8000/api/v1/jobs | python3 -m json.tool
```

### Python Standalone Script (`ingest_standalone.py`)

The standalone script runs the full ingestion pipeline directly without the API or worker.

**Pros:**
- No worker needed (can stop aaa-worker container)
- Full control over system resources (nice, ionice, etc.)
- Can run with very low priority

**Cons:**
- Requires Python environment with all dependencies
- Must run on same machine as the data
- Won't show up in API job status

**Usage:**
```bash
# Basic (outside Docker, needs virtualenv active)
python app/scripts/ingest_standalone.py --project "My Project"

# With low priority (won't interfere with other work)
nice -n 19 ionice -c 3 python app/scripts/ingest_standalone.py --project "My Project"

# In background with log
nohup nice -n 19 python app/scripts/ingest_standalone.py --project "My Project" > ingest.log 2>&1 &

# Specific files only
python app/scripts/ingest_standalone.py --project "My Project" --files report.pdf specs.docx

# Validate environment first
python app/scripts/ingest_standalone.py --validate-only
```

## Resource Management

### Limit Worker Resource Usage

If you want the worker running but competing less with your other work:

```bash
# Limit CPU cores
docker update --cpus="2" aaa-worker

# Lower process priority inside container
docker exec aaa-worker renice -n 19 -p 1

# Limit GPU memory (if using CUDA)
docker update --gpus '"device=0,capabilities=compute"' aaa-worker

# Restart worker with new limits
docker restart aaa-worker
```

### Stop Worker Entirely

If you want all resources free:

```bash
# Stop worker (ingestion won't work via API)
docker stop aaa-worker

# Use standalone script instead
python app/scripts/ingest_standalone.py --project "My Project"

# Restart later when needed
docker start aaa-worker
```

## Checking Progress

### Bash Script Method
The script shows progress automatically. To check later:

```bash
# List all jobs
curl http://localhost:8000/api/v1/jobs | python3 -m json.tool

# Check specific job
curl http://localhost:8000/api/v1/jobs/JOB_ID | python3 -m json.tool
```

### Standalone Script Method
Progress is printed directly to stdout/log file.

## Troubleshooting

### "Module not found" (Standalone Script)
You need to activate your Python virtualenv with all backend dependencies:
```bash
cd /path/to/project-library
source venv/bin/activate  # Or wherever your venv is
python app/scripts/ingest_standalone.py --validate-only
```

### "Project directory not found"
Make sure documents are uploaded first:
```bash
ls -la data/raw_docs/
# Should show your project folder
```

### Worker is using too much GPU
```bash
# Check GPU usage
docker exec aaa-worker nvidia-smi

# Reduce n_gpu_layers in config.yaml
# Or stop worker and use standalone script
docker stop aaa-worker
```

## See Also

- Full ingestion docs: `/docs` endpoint
- Job status API: `GET /api/v1/jobs/{job_id}`
- Admin dashboard: Press `Ctrl+Shift+A` in web UI
