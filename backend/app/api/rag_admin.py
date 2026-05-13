"""Admin RAG upload endpoints."""

from __future__ import annotations

import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from backend.app.api.deps import get_current_admin_user
from backend.app.models.user import User
from backend.app.rag.ingest_upload import ingest_file_safe

router = APIRouter(prefix="/admin/rag", tags=["admin-rag"])

_ALLOWED = {".txt", ".csv", ".xlsx"}
_MAX_BYTES = 25 * 1024 * 1024
_tasks: dict[str, dict] = {}
_lock = threading.Lock()


def _run_ingest(task_id: str, tmp_path: Path, filename: str, uploaded_by: str) -> None:
    try:
        result = ingest_file_safe(tmp_path)
        result["filename"] = filename
        result["uploaded_by"] = uploaded_by
        with _lock:
            _tasks[task_id] = {"status": "completed", "result": result}
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


@router.post("/upload")
def upload_rag_document(
    file: UploadFile = File(...),
    admin: User = Depends(get_current_admin_user),
):
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少文件名")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"仅支持 {', '.join(sorted(_ALLOWED))}",
        )
    raw = file.file.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="文件超过 25MB 限制",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)

    task_id = uuid.uuid4().hex
    with _lock:
        _tasks[task_id] = {"status": "queued", "filename": file.filename}

    worker = threading.Thread(
        target=_run_ingest,
        args=(task_id, tmp_path, file.filename, admin.username),
        daemon=True,
    )
    worker.start()
    return {"task_id": task_id, "status": "queued", "filename": file.filename}


@router.get("/tasks/{task_id}")
def get_rag_upload_task(
    task_id: str,
    admin: User = Depends(get_current_admin_user),
):
    with _lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return task
