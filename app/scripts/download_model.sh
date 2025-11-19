#!/bin/bash
# Download Llama-3.2-3B-Instruct model for local Q&A

set -e

MODEL_DIR="/home/jack/lib/project-library/data/models"
MODEL_FILE="$MODEL_DIR/Llama-3.2-3B-Instruct-Q6_K.gguf"
MODEL_URL="https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q6_K.gguf"

echo "=========================================="
echo "DOWNLOADING LLM MODEL"
echo "=========================================="
echo ""
echo "Model: Llama-3.2-3B-Instruct-Q6_K"
echo "Size: ~2.0 GB"
echo "Location: $MODEL_FILE"
echo ""

# Create directory
mkdir -p "$MODEL_DIR"

# Check if already exists
if [ -f "$MODEL_FILE" ]; then
    echo "[OK] Model already exists!"
    ls -lh "$MODEL_FILE"
    exit 0
fi

# Download
echo "Downloading model (this will take 5-10 minutes)..."
echo ""

if command -v wget &> /dev/null; then
    wget --progress=bar:force:noscroll -O "$MODEL_FILE" "$MODEL_URL"
elif command -v curl &> /dev/null; then
    curl -L --progress-bar -o "$MODEL_FILE" "$MODEL_URL"
else
    echo "[FAIL] Neither wget nor curl found. Install one:"
    echo "  sudo apt install wget"
    exit 1
fi

echo ""
echo "[OK] Download complete!"
ls -lh "$MODEL_FILE"
echo ""
echo "Restart the backend to load the model:"
echo "  cd app/backend"
echo "  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
