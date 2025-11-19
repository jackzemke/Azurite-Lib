#!/usr/bin/env python3
"""
Sanity check script.

Validates environment and runs dry-run tests.
"""

import sys
from pathlib import Path
import subprocess


def check_model_file():
    """Check if LLM model file exists."""
    model_path = Path("/home/jack/lib/project-library/data/models/Llama-3.2-3B-Instruct-Q6_K.gguf")
    
    if model_path.exists():
        print("[OK] Model file found")
        return True
    else:
        print("[WARN] Model file not found (will run in stub mode)")
        return False


def check_tesseract():
    """Check if Tesseract is installed."""
    try:
        result = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            version = result.stdout.split('\n')[0]
            print(f"[OK] Tesseract installed: {version}")
            return True
        else:
            print("[FAIL] Tesseract not found")
            return False
    except FileNotFoundError:
        print("[FAIL] Tesseract not found")
        return False


def check_python_packages():
    """Check if required Python packages are installed."""
    # Map of package names to their import names
    required = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "pdfplumber": "pdfplumber",
        "python-docx": "docx",
        "pytesseract": "pytesseract",
        "sentence-transformers": "sentence_transformers",
        "chromadb": "chromadb",
    }
    
    missing = []
    for package, import_name in required.items():
        try:
            __import__(import_name)
            print(f"[OK] {package}")
        except ImportError:
            print(f"[FAIL] {package} not installed")
            missing.append(package)
    
    if missing:
        print(f"\nInstall missing packages:")
        print(f"  pip install {' '.join(missing)}")
        return False
    
    return True


def check_directories():
    """Check if data directories exist."""
    base = Path("/home/jack/lib/project-library/data")
    
    dirs = [
        "raw_docs",
        "ocr",
        "text",
        "chunks",
        "embeddings",
        "index/chroma",
        "models",
        "logs",
    ]
    
    for dir_name in dirs:
        dir_path = base / dir_name
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"[OK] {dir_path}")
    
    return True


def main():
    print("="*60)
    print("SANITY CHECK")
    print("="*60)
    
    print("\n1. Checking model file...")
    model_ok = check_model_file()
    
    print("\n2. Checking Tesseract OCR...")
    tesseract_ok = check_tesseract()
    
    print("\n3. Checking Python packages...")
    packages_ok = check_python_packages()
    
    print("\n4. Checking data directories...")
    dirs_ok = check_directories()
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    if packages_ok and dirs_ok:
        print("[OK] Environment ready")
        if not model_ok:
            print("[WARN] Running in STUB MODE (no model file)")
        if not tesseract_ok:
            print("[WARN] OCR will fail (Tesseract not found)")
        return 0
    else:
        print("[FAIL] Environment not ready")
        print("Fix the errors above and try again.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
