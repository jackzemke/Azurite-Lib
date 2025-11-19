#!/bin/bash
# Sample data loader script
#
# Copies sample documents to the data directory for testing.

set -e

echo "Loading sample data..."

BASE_DIR="/home/jack/lib/project-library"
SAMPLE_A_DIR="$BASE_DIR/data/raw_docs/sample_proj_A"
SAMPLE_B_DIR="$BASE_DIR/data/raw_docs/sample_proj_B"

# Create directories
mkdir -p "$SAMPLE_A_DIR"
mkdir -p "$SAMPLE_B_DIR"

echo "Sample project directories created:"
echo "  - $SAMPLE_A_DIR"
echo "  - $SAMPLE_B_DIR"

echo ""
echo "To test the system:"
echo "1. Place sample documents in these directories"
echo "2. Run: python app/scripts/ingest_cli.py --project sample_proj_A"
echo "3. Run: curl -X POST http://127.0.0.1:8000/api/v1/query -H 'Content-Type: application/json' -d '{\"project_id\":\"sample_proj_A\",\"query\":\"test\"}'"
echo ""
echo "Note: This script only creates directories. Add your own PDF, DOCX, image files to test."
