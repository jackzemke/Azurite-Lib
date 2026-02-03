#!/usr/bin/env python
"""
RQ Worker Runner for background ingestion jobs.

Usage:
    python run_worker.py

Or with multiple workers:
    python run_worker.py --workers 2

Requirements:
    - Redis server running on localhost:6379 (or set REDIS_HOST/REDIS_PORT)
    - Backend dependencies installed

The worker processes jobs from the 'ingestion' queue.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def run_worker():
    """Start a single RQ worker."""
    try:
        from redis import Redis
        from rq import Worker, Queue
    except ImportError:
        logger.error("Redis and RQ packages not installed. Run: pip install redis rq")
        sys.exit(1)
    
    redis_host = os.environ.get("REDIS_HOST", "localhost")
    redis_port = int(os.environ.get("REDIS_PORT", "6379"))
    
    logger.info(f"Connecting to Redis at {redis_host}:{redis_port}")
    
    try:
        conn = Redis(host=redis_host, port=redis_port)
        conn.ping()
    except Exception as e:
        logger.error(f"Cannot connect to Redis: {e}")
        logger.error("Make sure Redis is running: redis-server or docker run -d -p 6379:6379 redis")
        sys.exit(1)
    
    queue = Queue('ingestion', connection=conn)
    worker = Worker([queue], connection=conn)
    
    logger.info("Starting RQ worker for 'ingestion' queue...")
    logger.info("Press Ctrl+C to stop")
    
    worker.work(with_scheduler=True)


def main():
    parser = argparse.ArgumentParser(description="Run RQ workers for background ingestion")
    parser.add_argument("--workers", type=int, default=1, help="Number of workers to start")
    args = parser.parse_args()
    
    if args.workers == 1:
        run_worker()
    else:
        # For multiple workers, use subprocess
        import subprocess
        processes = []
        for i in range(args.workers):
            logger.info(f"Starting worker {i+1}/{args.workers}")
            p = subprocess.Popen([sys.executable, __file__])
            processes.append(p)
        
        try:
            for p in processes:
                p.wait()
        except KeyboardInterrupt:
            logger.info("Stopping workers...")
            for p in processes:
                p.terminate()


if __name__ == "__main__":
    main()
