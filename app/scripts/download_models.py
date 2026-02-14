#!/usr/bin/env python3
"""
Download and verify models for the AAA pipeline.

Downloads:
1. Meta-Llama-3.1-8B-Instruct-Q6_K.gguf (~6.6GB) - LLM for Q&A
2. nomic-ai/nomic-embed-text-v1.5 (~275MB) - Embedding model (768-dim)
3. cross-encoder/ms-marco-MiniLM-L-6-v2 (~80MB) - Reranker

Usage:
    python app/scripts/download_models.py
    python app/scripts/download_models.py --llm-only
    python app/scripts/download_models.py --embeddings-only
    python app/scripts/download_models.py --verify
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = PROJECT_ROOT / "data" / "models"

LLM_MODEL = {
    "name": "Meta-Llama-3.1-8B-Instruct-Q6_K.gguf",
    "url": "https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q6_K.gguf",
    "size_gb": 6.6,
}

EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def download_llm():
    """Download the GGUF LLM model."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / LLM_MODEL["name"]

    if model_path.exists():
        size_gb = model_path.stat().st_size / (1024**3)
        print(f"[OK] LLM model already exists: {model_path} ({size_gb:.1f}GB)")
        return True

    print(f"Downloading {LLM_MODEL['name']} (~{LLM_MODEL['size_gb']}GB)...")
    print(f"  URL: {LLM_MODEL['url']}")
    print(f"  Destination: {model_path}")
    print()

    try:
        subprocess.run(
            ["wget", "--progress=bar:force:noscroll", "-O", str(model_path), LLM_MODEL["url"]],
            check=True,
        )
    except FileNotFoundError:
        try:
            subprocess.run(
                ["curl", "-L", "--progress-bar", "-o", str(model_path), LLM_MODEL["url"]],
                check=True,
            )
        except FileNotFoundError:
            print("[FAIL] Neither wget nor curl found. Install one: sudo apt install wget")
            return False

    if model_path.exists():
        size_gb = model_path.stat().st_size / (1024**3)
        print(f"[OK] LLM model downloaded ({size_gb:.1f}GB)")
        return True
    else:
        print("[FAIL] Download failed")
        return False


def download_embedding_model():
    """Download the embedding model via sentence-transformers."""
    print(f"Downloading embedding model: {EMBEDDING_MODEL}")
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(EMBEDDING_MODEL, trust_remote_code=True)
        # Quick verification
        test_emb = model.encode(["search_query: test"])
        dim = test_emb.shape[1] if len(test_emb.shape) > 1 else len(test_emb[0])
        print(f"[OK] Embedding model loaded, dim={dim}")
        if dim != 768:
            print(f"[WARN] Expected 768 dimensions, got {dim}")
        return True
    except Exception as e:
        print(f"[FAIL] Could not download embedding model: {e}")
        return False


def download_reranker():
    """Download the cross-encoder reranker model."""
    print(f"Downloading reranker model: {RERANKER_MODEL}")
    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder(RERANKER_MODEL)
        # Quick verification
        score = model.predict([("query", "document")])
        print(f"[OK] Reranker model loaded, test score={score[0]:.4f}")
        return True
    except Exception as e:
        print(f"[FAIL] Could not download reranker model: {e}")
        return False


def verify_models():
    """Verify all models are available and working."""
    print("=" * 50)
    print("MODEL VERIFICATION")
    print("=" * 50)
    print()

    all_ok = True

    # 1. LLM
    model_path = MODELS_DIR / LLM_MODEL["name"]
    if model_path.exists():
        size_gb = model_path.stat().st_size / (1024**3)
        print(f"[OK] LLM: {model_path.name} ({size_gb:.1f}GB)")
    else:
        print(f"[MISSING] LLM: {model_path}")
        all_ok = False

    # 2. Embedding model
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(EMBEDDING_MODEL, trust_remote_code=True)
        test = model.encode(["search_document: test", "search_query: test"])
        print(f"[OK] Embedder: {EMBEDDING_MODEL} (dim={test.shape[1]})")
    except Exception as e:
        print(f"[MISSING] Embedder: {EMBEDDING_MODEL} ({e})")
        all_ok = False

    # 3. Reranker
    try:
        from sentence_transformers import CrossEncoder
        CrossEncoder(RERANKER_MODEL)
        print(f"[OK] Reranker: {RERANKER_MODEL}")
    except Exception as e:
        print(f"[MISSING] Reranker: {RERANKER_MODEL} ({e})")
        all_ok = False

    print()
    if all_ok:
        print("All models verified.")
    else:
        print("Some models are missing. Run: python app/scripts/download_models.py")

    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Download AAA pipeline models")
    parser.add_argument("--llm-only", action="store_true", help="Download only the LLM model")
    parser.add_argument("--embeddings-only", action="store_true", help="Download only embedding + reranker models")
    parser.add_argument("--verify", action="store_true", help="Verify models without downloading")
    args = parser.parse_args()

    if args.verify:
        success = verify_models()
        sys.exit(0 if success else 1)

    results = []

    if args.llm_only:
        results.append(("LLM", download_llm()))
    elif args.embeddings_only:
        results.append(("Embedder", download_embedding_model()))
        results.append(("Reranker", download_reranker()))
    else:
        # Download all
        results.append(("LLM", download_llm()))
        results.append(("Embedder", download_embedding_model()))
        results.append(("Reranker", download_reranker()))

    print()
    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)
    for name, ok in results:
        status = "OK" if ok else "FAILED"
        print(f"  [{status}] {name}")

    if all(ok for _, ok in results):
        print()
        print("All downloads complete. Run --verify to confirm.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
