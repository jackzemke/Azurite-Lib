"""
Admin API endpoints for monitoring and service management.

Provides:
- Service status checks
- Log file listing and viewing
- Service start/stop (spawns subprocesses)
- Real-time log streaming via WebSocket
"""

import os
import json
import asyncio
import subprocess
import signal
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# Track managed processes
managed_processes: Dict[str, subprocess.Popen] = {}

# Base paths
DATA_DIR = Path("/home/jack/lib/project-library/data")
LOGS_DIR = DATA_DIR / "logs"
PROJECT_ROOT = Path("/home/jack/lib/project-library")


# ============================================================================
# Models
# ============================================================================

class ServiceStatus(BaseModel):
    name: str
    status: str  # "running", "stopped", "unknown"
    pid: Optional[int] = None
    uptime_seconds: Optional[float] = None
    details: Optional[str] = None


class ServiceAction(BaseModel):
    action: str  # "start", "stop", "restart"


class LogFile(BaseModel):
    name: str
    path: str
    size_bytes: int
    modified_at: str
    type: str  # "ingest_report", "query_log", "other"


class LogContent(BaseModel):
    name: str
    content: str
    lines: int
    truncated: bool


# ============================================================================
# Service Definitions
# ============================================================================

SERVICES = {
    "backend": {
        "name": "Backend (FastAPI)",
        "check_cmd": "curl -s http://localhost:8000/api/v1/health",
        "start_cmd": "cd /home/jack/lib/project-library/app/backend && source ../../.venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000",
        "port": 8000,
    },
    "frontend": {
        "name": "Frontend (Vite)",
        "check_url": "http://localhost:5173",
        "start_cmd": "cd /home/jack/lib/project-library/app/frontend && npm run dev",
        "port": 5173,
    },
    "redis": {
        "name": "Redis",
        "check_cmd": "redis-cli ping",
        "start_cmd": "redis-server",
        "port": 6379,
    },
    "rq_worker": {
        "name": "RQ Worker",
        "check_cmd": "pgrep -f 'rq worker'",
        "start_cmd": "cd /home/jack/lib/project-library && source .venv/bin/activate && python app/scripts/run_worker.py",
        "port": None,
    },
}


# ============================================================================
# Service Status Endpoints
# ============================================================================

@router.get("/services", response_model=List[ServiceStatus])
async def list_services():
    """Get status of all services."""
    statuses = []
    
    for service_id, config in SERVICES.items():
        status = await check_service_status(service_id, config)
        statuses.append(status)
    
    return statuses


@router.get("/services/{service_id}", response_model=ServiceStatus)
async def get_service_status(service_id: str):
    """Get status of a specific service."""
    if service_id not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service_id}")
    
    return await check_service_status(service_id, SERVICES[service_id])


async def check_service_status(service_id: str, config: dict) -> ServiceStatus:
    """Check if a service is running."""
    name = config["name"]
    
    # Check if we're managing this process
    if service_id in managed_processes:
        proc = managed_processes[service_id]
        if proc.poll() is None:  # Still running
            return ServiceStatus(
                name=name,
                status="running",
                pid=proc.pid,
                details="Managed by admin dashboard"
            )
        else:
            # Process ended
            del managed_processes[service_id]
    
    # Try check command
    if "check_cmd" in config:
        try:
            result = subprocess.run(
                config["check_cmd"],
                shell=True,
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return ServiceStatus(name=name, status="running", details="Responding")
            else:
                return ServiceStatus(name=name, status="stopped")
        except subprocess.TimeoutExpired:
            return ServiceStatus(name=name, status="unknown", details="Health check timed out")
        except Exception as e:
            return ServiceStatus(name=name, status="unknown", details=str(e))
    
    # Fallback: check port
    if config.get("port"):
        try:
            result = subprocess.run(
                f"lsof -i :{config['port']} | grep LISTEN",
                shell=True,
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return ServiceStatus(name=name, status="running", details=f"Port {config['port']} in use")
            else:
                return ServiceStatus(name=name, status="stopped")
        except:
            pass
    
    return ServiceStatus(name=name, status="unknown")


@router.post("/services/{service_id}")
async def control_service(service_id: str, action: ServiceAction):
    """Start, stop, or restart a service."""
    if service_id not in SERVICES:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service_id}")
    
    config = SERVICES[service_id]
    
    if action.action == "start":
        return await start_service(service_id, config)
    elif action.action == "stop":
        return await stop_service(service_id, config)
    elif action.action == "restart":
        await stop_service(service_id, config)
        await asyncio.sleep(1)
        return await start_service(service_id, config)
    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action.action}")


async def start_service(service_id: str, config: dict) -> dict:
    """Start a service as a subprocess."""
    if service_id in managed_processes:
        proc = managed_processes[service_id]
        if proc.poll() is None:
            return {"status": "already_running", "pid": proc.pid}
    
    if "start_cmd" not in config:
        raise HTTPException(status_code=400, detail="No start command configured")
    
    # Create log file for this service
    log_file = LOGS_DIR / f"{service_id}.log"
    
    try:
        with open(log_file, "a") as f:
            f.write(f"\n--- Service started at {datetime.now().isoformat()} ---\n")
        
        proc = subprocess.Popen(
            config["start_cmd"],
            shell=True,
            stdout=open(log_file, "a"),
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,  # Create new process group
        )
        
        managed_processes[service_id] = proc
        logger.info(f"Started {service_id} with PID {proc.pid}")
        
        return {"status": "started", "pid": proc.pid, "log_file": str(log_file)}
    
    except Exception as e:
        logger.error(f"Failed to start {service_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def stop_service(service_id: str, config: dict) -> dict:
    """Stop a managed service."""
    if service_id in managed_processes:
        proc = managed_processes[service_id]
        if proc.poll() is None:
            try:
                # Kill the process group
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception as e:
                logger.warning(f"Error stopping {service_id}: {e}")
            
            del managed_processes[service_id]
            return {"status": "stopped"}
    
    # Try to find and kill by port
    if config.get("port"):
        try:
            subprocess.run(
                f"fuser -k {config['port']}/tcp",
                shell=True,
                timeout=5
            )
            return {"status": "stopped", "details": f"Killed process on port {config['port']}"}
        except:
            pass
    
    return {"status": "not_running"}


# ============================================================================
# Log File Endpoints
# ============================================================================

@router.get("/logs", response_model=List[LogFile])
async def list_log_files():
    """List all available log files."""
    files = []
    
    if LOGS_DIR.exists():
        for path in sorted(LOGS_DIR.iterdir()):
            if path.is_file():
                stat = path.stat()
                
                # Determine type
                if path.name.startswith("ingest_report_"):
                    log_type = "ingest_report"
                elif path.name == "queries.log":
                    log_type = "query_log"
                elif path.suffix == ".log":
                    log_type = "service_log"
                else:
                    log_type = "other"
                
                files.append(LogFile(
                    name=path.name,
                    path=str(path),
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    type=log_type,
                ))
    
    return files


@router.get("/logs/{log_name}", response_model=LogContent)
async def get_log_content(
    log_name: str,
    tail: int = Query(default=500, description="Number of lines from end"),
):
    """Get content of a log file."""
    log_path = LOGS_DIR / log_name
    
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {log_name}")
    
    if not log_path.is_relative_to(LOGS_DIR):
        raise HTTPException(status_code=403, detail="Access denied")
    
    try:
        # For JSON files, pretty print
        if log_name.endswith(".json"):
            with open(log_path) as f:
                data = json.load(f)
            content = json.dumps(data, indent=2)
            lines = content.count("\n") + 1
            return LogContent(name=log_name, content=content, lines=lines, truncated=False)
        
        # For text files, tail
        with open(log_path) as f:
            all_lines = f.readlines()
        
        if len(all_lines) > tail:
            content = "".join(all_lines[-tail:])
            truncated = True
        else:
            content = "".join(all_lines)
            truncated = False
        
        return LogContent(
            name=log_name,
            content=content,
            lines=len(all_lines),
            truncated=truncated,
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# WebSocket Log Streaming
# ============================================================================

class LogStreamer:
    """Streams log file changes via WebSocket."""
    
    def __init__(self, websocket: WebSocket, log_path: Path):
        self.websocket = websocket
        self.log_path = log_path
        self.running = True
    
    async def stream(self):
        """Stream new lines as they're added to the log file."""
        try:
            # Start at end of file
            if self.log_path.exists():
                with open(self.log_path) as f:
                    f.seek(0, 2)  # Seek to end
                    position = f.tell()
            else:
                position = 0
            
            while self.running:
                if self.log_path.exists():
                    with open(self.log_path) as f:
                        f.seek(position)
                        new_content = f.read()
                        if new_content:
                            await self.websocket.send_text(new_content)
                            position = f.tell()
                
                await asyncio.sleep(0.5)  # Poll every 500ms
        
        except WebSocketDisconnect:
            self.running = False
        except Exception as e:
            logger.error(f"Log streaming error: {e}")
            self.running = False


@router.websocket("/logs/{log_name}/stream")
async def stream_log(websocket: WebSocket, log_name: str):
    """WebSocket endpoint for real-time log streaming."""
    await websocket.accept()
    
    log_path = LOGS_DIR / log_name
    
    if not log_path.is_relative_to(LOGS_DIR):
        await websocket.close(code=1008, reason="Access denied")
        return
    
    streamer = LogStreamer(websocket, log_path)
    
    try:
        await streamer.stream()
    except WebSocketDisconnect:
        pass
    finally:
        streamer.running = False


# ============================================================================
# System Info
# ============================================================================

@router.get("/system")
async def get_system_info():
    """Get system information."""
    import platform
    import psutil
    
    # Disk usage for data directory
    disk = psutil.disk_usage(str(DATA_DIR))
    
    # Memory
    mem = psutil.virtual_memory()
    
    # ChromaDB stats
    chroma_size = sum(f.stat().st_size for f in (DATA_DIR / "index" / "chroma").rglob("*") if f.is_file()) if (DATA_DIR / "index" / "chroma").exists() else 0
    
    return {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": psutil.cpu_count(),
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory": {
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent": round(disk.percent, 1),
        },
        "data_directory": str(DATA_DIR),
        "chroma_size_mb": round(chroma_size / (1024**2), 2),
    }
