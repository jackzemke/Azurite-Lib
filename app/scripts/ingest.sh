#!/bin/bash
# Quick CLI helper for document ingestion
#
# Usage:
#   ./ingest.sh "Project Name (123456)"
#
# This triggers async ingestion via the API, so the worker container
# must be running. Progress is shown periodically.

set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
PROJECT_ID="$1"

if [ -z "$PROJECT_ID" ]; then
  echo "Usage: $0 'Project Name'"
  echo "Example: $0 'Wastewater Treatment (1234567)'"
  exit 1
fi

echo "Starting ingestion for: $PROJECT_ID"
echo "API: $API_URL"
echo ""

# Trigger async ingestion
RESPONSE=$(curl -s -X POST "$API_URL/api/v1/projects/$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$PROJECT_ID'''))")/ingest/async")

JOB_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('job_id', ''))")

if [ -z "$JOB_ID" ]; then
  echo "❌ Failed to start ingestion job"
  echo "$RESPONSE"
  exit 1
fi

echo "✓ Job queued: $JOB_ID"
echo ""
echo "Monitoring progress (Ctrl+C to stop monitoring, job continues)..."
echo ""

# Poll job status
while true; do
  STATUS=$(curl -s "$API_URL/api/v1/jobs/$JOB_ID")

  STATE=$(echo "$STATUS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('state', 'unknown'))")
  PROGRESS=$(echo "$STATUS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('progress', 0))")
  MESSAGE=$(echo "$STATUS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('message', ''))")
  FILES_PROCESSED=$(echo "$STATUS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('files_processed', 0))")
  CHUNKS=$(echo "$STATUS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('chunks_created', 0))")

  # Format progress bar (50 chars)
  FILLED=$( python3 -c "print(int($PROGRESS / 2))" )
  BAR=$(python3 -c "print('█' * $FILLED + '░' * (50 - $FILLED))")

  printf "\r[%s] %5.1f%% | %s files | %s chunks | %s  " "$BAR" "$PROGRESS" "$FILES_PROCESSED" "$CHUNKS" "$MESSAGE"

  if [ "$STATE" = "finished" ]; then
    echo ""
    echo ""
    echo "✅ Ingestion complete!"
    DURATION=$(echo "$STATUS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('duration_seconds', 0))")
    echo "   Files: $FILES_PROCESSED"
    echo "   Chunks: $CHUNKS"
    echo "   Duration: ${DURATION}s"
    break
  elif [ "$STATE" = "failed" ]; then
    echo ""
    echo ""
    echo "❌ Ingestion failed"
    ERRORS=$(echo "$STATUS" | python3 -c "import sys, json; errors = json.load(sys.stdin).get('errors', []); print(', '.join(errors[:3]))")
    echo "   $ERRORS"
    exit 1
  fi

  sleep 2
done
