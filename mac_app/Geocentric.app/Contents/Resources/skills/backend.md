# Backend Architecture & Security Skill

## Purpose
Use this skill when building APIs, routing engines, databases, long-running processes, file-management scripts, or command handlers.

## 1. Core Directives
1. **Security & Boundary Isolation**: Never attempt sandbox escapes. Keep all file operations strictly inside the user's workspace boundaries. Check for path traversals (like `/../`) and validate resolved paths.
2. **Error Resiliency**: Wrap critical database/network code in try/except blocks. Provide meaningful developer logging while returning clean error codes/JSON schemas to the frontend client.
3. **Background Process Controls**: 
   - Launch long-running servers using `<run_bg_command>`.
   - Inspect their running states using `<check_process pid="..." />`.
   - Stop them securely using `<kill_process pid="..." />`.
4. **Data Schemas**: Enforce rigorous data validation utilizing strict Pydantic models, secure database queries, and proper transaction commits.

## 2. Structural Architecture
A professional Python backend structure should always be organized as follows:
```
├── app/
│   ├── config.py          # Environment values & paths
│   ├── models/            # SQLAlchemy or Pydantic DB definitions
│   ├── routes/            # Module endpoints (e.g. users, chats, jobs)
│   ├── services/          # Pure computational business logic
│   └── database.py        # SQLite or PostgreSQL connection lifecycle
├── server.py              # Main execution entrypoint
└── requirements.txt       # Strict versioned packages
```

## 3. High-Quality Code Examples

### Secure Path Validation & File Operations
```python
from pathlib import Path
import os

def secure_workspace_path(workspace_dir: Path, user_file: str) -> Path:
    """
    Safely resolves a file path within a sandbox boundary to prevent path traversal.
    """
    resolved_root = workspace_dir.resolve()
    target_path = (resolved_root / user_file).resolve()
    
    # Check boundary escape
    if not target_path.is_relative_to(resolved_root):
        raise PermissionError(f"Access Denied: Path traversal detected for '{user_file}'")
    return target_path

def read_user_file(workspace_dir: Path, filename: str) -> str:
    try:
        safe_path = secure_workspace_path(workspace_dir, filename)
        if not safe_path.exists() or not safe_path.is_file():
            return f"ERROR: File '{filename}' not found."
        return safe_path.read_text(encoding="utf-8")
    except PermissionError as pe:
        return str(pe)
    except Exception as e:
        return f"ERROR reading file: {str(e)}"
```

### Async Fast API Endpoint with Background Job Launching
```python
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uuid
import asyncio

app = FastAPI()

class JobRequest(BaseModel):
    task_name: str
    params: dict

async def run_heavy_task(job_id: str, params: dict):
    # Perform intensive task
    await asyncio.sleep(10)
    print(f"Job {job_id} successfully completed.")

@app.post("/api/jobs")
async def start_job(req: JobRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    background_tasks.add_task(run_heavy_task, job_id, req.params)
    return {"job_id": job_id, "status": "queued"}
```
