#!/bin/bash
# Quick start script for Project Library MVP
#
# This script validates the environment and provides next steps.

set -e

echo "=========================================="
echo "PROJECT LIBRARY MVP - QUICK START"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Repository: $(pwd)"
echo ""

# Step 1: Check Python
echo "[1/6] Checking Python..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo -e "${GREEN}[OK]${NC} Python found: $PYTHON_VERSION"
else
    echo -e "${RED}[FAIL]${NC} Python 3 not found"
    exit 1
fi
echo ""

# Step 2: Check virtual environment
echo "[2/6] Checking virtual environment..."
if [ -d ".venv" ]; then
    echo -e "${GREEN}[OK]${NC} Virtual environment exists"
else
    echo -e "${YELLOW}[WARN]${NC} Virtual environment not found"
    echo "   Creating virtual environment..."
    python3 -m venv .venv
    echo -e "${GREEN}[OK]${NC} Created .venv"
fi
echo ""

# Step 3: Activate and install dependencies
echo "[3/6] Installing Python dependencies..."
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r app/backend/requirements.txt
echo -e "${GREEN}[OK]${NC} Dependencies installed"
echo ""

# Step 4: Check Tesseract
echo "[4/6] Checking Tesseract OCR..."
if command -v tesseract &> /dev/null; then
    TESSERACT_VERSION=$(tesseract --version 2>&1 | head -1)
    echo -e "${GREEN}[OK]${NC} Tesseract found: $TESSERACT_VERSION"
else
    echo -e "${YELLOW}[WARN]${NC} Tesseract not found (OCR will fail)"
    echo "   Install: sudo apt install tesseract-ocr"
fi
echo ""

# Step 5: Check model file
echo "[5/6] Checking LLM model file..."
MODEL_PATH="data/models/Llama-3.2-3B-Instruct-Q6_K.gguf"
if [ -f "$MODEL_PATH" ]; then
    MODEL_SIZE=$(du -h "$MODEL_PATH" | cut -f1)
    echo -e "${GREEN}[OK]${NC} Model file found: $MODEL_SIZE"
else
    echo -e "${YELLOW}[WARN]${NC} Model file not found (will run in STUB MODE)"
    echo "   Place model at: $MODEL_PATH"
fi
echo ""

# Step 6: Run sanity check
echo "[6/6] Running sanity check..."
python app/scripts/sanity_check.py
echo ""

# Next steps
echo "=========================================="
echo "SETUP COMPLETE!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Start the backend:"
echo "   cd app/backend"
echo "   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
echo ""
echo "2. (Optional) Start the frontend:"
echo "   cd app/frontend"
echo "   npm install"
echo "   npm run dev"
echo ""
echo "3. Test the API:"
echo "   curl http://127.0.0.1:8000/api/v1/health"
echo ""
echo "4. Upload sample documents:"
echo "   mkdir -p data/raw_docs/test_proj"
echo "   # Copy your PDF/DOCX files to data/raw_docs/test_proj/"
echo ""
echo "5. Ingest documents:"
echo "   python app/scripts/ingest_cli.py --project test_proj"
echo ""
echo "6. Query documents:"
echo "   curl -X POST http://127.0.0.1:8000/api/v1/query \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"project_id\":\"test_proj\",\"query\":\"YOUR QUESTION\",\"k\":6}'"
echo ""
echo "Documentation:"
echo "   - README.md - Full setup guide"
echo "   - DELIVERY_SUMMARY.md - Complete feature list"
echo "   - INGESTION_CHECKLIST.md - Validation steps"
echo ""
echo "Troubleshooting:"
echo "   - Check app/backend/app/main.py for API entry point"
echo "   - View logs at data/logs/"
echo "   - Run tests: pytest -v"
echo ""
