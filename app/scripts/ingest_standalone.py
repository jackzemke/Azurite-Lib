#!/usr/bin/env python3
"""
Standalone CLI ingestion tool that runs directly without the API server.

This script ingests documents without requiring the FastAPI server or Redis to be running.
It uses the same pipeline logic as the background worker but runs synchronously with progress output.

Usage (inside Docker container - RECOMMENDED):
    # Basic usage
    docker exec aaa-backend python app/scripts/ingest_standalone.py --project "My Project (1234567)"

    # With low priority (won't overload system)
    docker exec aaa-backend nice -n 19 python app/scripts/ingest_standalone.py --project "My Project"

    # Run in background
    docker exec -d aaa-backend nice -n 19 python app/scripts/ingest_standalone.py --project "My Project"

Usage (outside Docker - requires dependencies):
    # Activate virtualenv first, then:
    python app/scripts/ingest_standalone.py --project "My Project (1234567)"

    # With low priority
    nice -n 19 ionice -c 3 python app/scripts/ingest_standalone.py --project "My Project"

    # In background with log
    nohup nice -n 19 python app/scripts/ingest_standalone.py --project "My Project" > ingest.log 2>&1 &

Requirements:
    - Python environment with all backend dependencies installed
    - config.yaml in app/backend/ or environment variables set
    - Raw documents already in data/raw_docs/{project_name}/
"""

import argparse
import sys
import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

# Add backend to path so we can import modules
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
BACKEND_DIR = PROJECT_ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Now import backend modules
from app.config import settings
from app.core.ingest_worker import run_ingest_job


class ProgressMonitor:
    """Simple progress monitor for standalone execution."""

    def __init__(self):
        self.last_progress = 0.0
        self.start_time = time.time()

    def update(self, progress: float, message: str):
        """Print progress update."""
        elapsed = time.time() - self.start_time

        # Progress bar (50 chars wide)
        filled = int(progress / 2)
        bar = "█" * filled + "░" * (50 - filled)

        # Format elapsed time
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"

        # Print with \r to overwrite previous line
        print(f"\r[{bar}] {progress:5.1f}% | {time_str} | {message}", end="", flush=True)

        self.last_progress = progress

        # Print newline on completion
        if progress >= 100:
            print()


def validate_environment():
    """Check that required paths and config exist."""
    errors = []

    # Check for config or env vars
    config_path = BACKEND_DIR / "config.yaml"
    if not config_path.exists() and not os.getenv("AAA_BASE_DIR"):
        errors.append(f"Config not found at {config_path} and AAA_BASE_DIR not set")

    # Check base paths exist
    if not settings.raw_docs_path.exists():
        errors.append(f"raw_docs directory not found: {settings.raw_docs_path}")

    # Check model exists (optional - can run in stub mode)
    if not settings.model_path_resolved.exists():
        print(f"⚠️  Warning: LLM model not found at {settings.model_path_resolved}")
        print("    Ingestion will continue (embeddings are separate), but queries won't work.")

    if errors:
        print("❌ Environment validation failed:")
        for error in errors:
            print(f"   - {error}")
        return False

    return True


def ingest_project_standalone(project_id: str, files: Optional[List[str]] = None) -> int:
    """
    Run ingestion directly without RQ/Redis.

    Args:
        project_id: Project folder name
        files: Optional list of specific files

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    print(f"\n{'='*70}")
    print(f"  Standalone Document Ingestion")
    print(f"{'='*70}")
    print(f"Project: {project_id}")

    project_dir = settings.raw_docs_path / project_id
    if not project_dir.exists():
        print(f"\n❌ Project directory not found: {project_dir}")
        print(f"   Upload files first or check the project name.")
        return 1

    if files:
        print(f"Files: {', '.join(files)}")
    else:
        print(f"Mode: Process all files in {project_dir}")

    print(f"\nConfig:")
    print(f"  - Base dir: {settings.base_dir}")
    print(f"  - Embedding model: {settings.embedding_model_name}")
    print(f"  - Chunk size: {settings.chunking_chunk_size_tokens} tokens")
    print(f"  - ChromaDB: {settings.chroma_db_path}")
    print()

    # Monkey-patch the update_progress function to use our monitor
    monitor = ProgressMonitor()

    import app.core.ingest_worker as worker_module
    original_update = worker_module.update_progress

    def monitor_update(progress: float, message: str, **kwargs):
        monitor.update(progress, message)
        # Still call original for any side effects (though there won't be any without RQ)
        original_update(progress, message, **kwargs)

    worker_module.update_progress = monitor_update

    # Run the ingestion job
    try:
        result = run_ingest_job(project_id, files)

        # Print final results
        print(f"\n{'='*70}")
        if result["success"]:
            print(f"✅ Ingestion Complete")
            print(f"\nResults:")
            print(f"  - Files processed: {result['files_processed']}")
            print(f"  - Files skipped: {result.get('files_skipped', 0)}")
            print(f"  - Files failed: {result.get('files_failed', 0)}")
            print(f"  - Chunks created: {result['chunks_created']}")
            print(f"  - Duration: {result['duration_seconds']:.1f}s")

            if result.get('errors'):
                print(f"\n⚠️  Errors ({len(result['errors'])}):")
                for error in result['errors'][:5]:  # Show first 5
                    print(f"   - {error}")
                if len(result['errors']) > 5:
                    print(f"   ... and {len(result['errors']) - 5} more")

            print(f"\nReport saved: data/logs/ingest_report_{project_id}.json")
            print(f"{'='*70}\n")
            return 0
        else:
            print(f"❌ Ingestion Failed")
            print(f"\nError: {result.get('error', 'Unknown error')}")
            print(f"Duration: {result['duration_seconds']:.1f}s")
            print(f"{'='*70}\n")
            return 1

    except KeyboardInterrupt:
        print(f"\n\n⚠️  Interrupted by user")
        return 130  # Standard exit code for SIGINT

    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Restore original function
        worker_module.update_progress = original_update


def main():
    parser = argparse.ArgumentParser(
        description="Standalone document ingestion (no Docker required)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples (inside Docker - RECOMMENDED):
  # Ingest entire project
  docker exec aaa-backend python app/scripts/ingest_standalone.py --project "My Project (1234567)"

  # With low priority (won't compete with queries)
  docker exec aaa-backend nice -n 19 python app/scripts/ingest_standalone.py --project "My Project"

  # Run in background (detached)
  docker exec -d aaa-backend nice -n 19 python app/scripts/ingest_standalone.py --project "My Project"

  # Check logs later
  docker logs aaa-backend --tail 100

Examples (outside Docker):
  # Ingest with specific files only
  python app/scripts/ingest_standalone.py --project "My Project" --files report.pdf

  # Run with low system priority
  nice -n 19 ionice -c 3 python app/scripts/ingest_standalone.py --project "My Project"

  # Run in background with log file
  nohup nice -n 19 python app/scripts/ingest_standalone.py --project "My Project" > ingest.log 2>&1 &
        """
    )

    parser.add_argument(
        "--project",
        required=True,
        help="Project folder name (e.g., 'My Project (1234567)')"
    )

    parser.add_argument(
        "--files",
        nargs="*",
        help="Specific files to process (relative to project dir). If omitted, processes all files."
    )

    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate environment, don't run ingestion"
    )

    args = parser.parse_args()

    # Validate environment
    print("Validating environment...")
    if not validate_environment():
        return 1

    print("✓ Environment OK\n")

    if args.validate_only:
        return 0

    # Run ingestion
    return ingest_project_standalone(args.project, args.files)


if __name__ == "__main__":
    sys.exit(main())
