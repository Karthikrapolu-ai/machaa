"""Local HTTP routes for the dashboard. There is no public deployment."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from machaa import __version__
from machaa.api.schemas import InstructionIn
from machaa.core.service import TaskService

router = APIRouter()
_TASK_ID = re.compile(r"^task_[0-9a-f]{32}$")
_NO_STORE = {"Cache-Control": "no-store"}


def _service(request: Request) -> TaskService:
    return request.app.state.service


def _task_or_404(task_id: str) -> str:
    if not _TASK_ID.fullmatch(task_id):
        raise HTTPException(status_code=404, detail="Task not found.")
    return task_id


@router.get("/api/health")
def health(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "product": "MACHAA",
        "version": __version__,
        "day": 2,
        "gemini_configured": bool(settings.gemini_api_key),
    }


@router.get("/api/tasks")
def list_tasks(request: Request) -> dict:
    return {"tasks": _service(request).list_recent()}


@router.post("/api/tasks", status_code=201)
async def create_task(body: InstructionIn, request: Request) -> dict:
    return await _service(request).submit(body.instruction)


@router.get("/api/tasks/{task_id}")
def get_task(task_id: str, request: Request) -> dict:
    _task_or_404(task_id)
    record = _service(request).get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return record


@router.post("/api/tasks/{task_id}/stop")
def stop_task(task_id: str, request: Request) -> dict:
    _task_or_404(task_id)
    record = _service(request).stop(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return record


@router.get("/api/tasks/{task_id}/report")
def get_report(task_id: str, request: Request) -> PlainTextResponse:
    _task_or_404(task_id)
    path = _service(request).artifact(task_id, "report")
    if path is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers=_NO_STORE,
    )


@router.get("/api/tasks/{task_id}/screenshot")
def get_screenshot(task_id: str, request: Request) -> FileResponse:
    _task_or_404(task_id)
    path = _service(request).artifact(task_id, "screenshot")
    if path is None:
        raise HTTPException(status_code=404, detail="Screenshot not found.")
    return FileResponse(path, media_type="image/png", headers=_NO_STORE)


@router.get("/api/tasks/{task_id}/document")
def get_document(task_id: str, request: Request) -> FileResponse:
    _task_or_404(task_id)
    path = _service(request).artifact(task_id, "document")
    if path is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="machaa-brief.docx",
        headers=_NO_STORE,
    )
