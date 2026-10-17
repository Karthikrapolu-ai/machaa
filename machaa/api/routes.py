"""Local HTTP routes for the dashboard. There is no public deployment."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from machaa import __version__
from machaa.api.schemas import EnabledIn, InstructionIn, TrackIn, UpdateIn
from machaa.core.errors import VoiceUnavailable
from machaa.core.service import TaskService
from machaa.voice.transcribe import MAX_AUDIO_BYTES, transcribe_audio, voice_ready

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
    service = _service(request)
    return {
        "status": "ok",
        "product": "MACHAA",
        "version": __version__,
        "day": 3,
        "gemini_configured": bool(settings.gemini_api_key),
        "desktop_enabled": bool(service.desktop_enabled),
        "companion_configured": bool(service.companion.configured()),
        "wake_enabled": bool(service.wake_enabled),
        "voice_ready": voice_ready(),
        **service.runtime_status(),
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


@router.post("/api/tasks/{task_id}/pause")
def pause_task(task_id: str, request: Request) -> dict:
    _task_or_404(task_id)
    record = _service(request).pause(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return record


@router.post("/api/tasks/{task_id}/approve")
def approve_task(task_id: str, request: Request) -> dict:
    _task_or_404(task_id)
    record = _service(request).approve(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return record


@router.post("/api/tasks/{task_id}/reject")
def reject_task(task_id: str, request: Request) -> dict:
    _task_or_404(task_id)
    record = _service(request).reject(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return record


@router.post("/api/desktop/permission")
def desktop_permission(body: EnabledIn, request: Request) -> dict:
    return _service(request).set_desktop(body.enabled)


@router.post("/api/companion/start")
def start_companion(request: Request) -> dict:
    return _service(request).companion_start_hint()


@router.post("/api/voice/wake")
def voice_wake(body: EnabledIn, request: Request) -> dict:
    return _service(request).set_wake(body.enabled)


@router.get("/api/updates")
def update_status(request: Request) -> dict:
    service = _service(request)
    status = service.check_updates()
    status["track"] = service.track_settings()
    return status


@router.post("/api/updates/track")
def update_track(body: TrackIn, request: Request) -> dict:
    return _service(request).set_track_branch(body.enabled, body.branch)


@router.post("/api/updates/apply")
def update_apply(body: UpdateIn, request: Request) -> dict:
    from machaa.update.engine import UpdateFailed
    from machaa.update.trust import UpdateRefused

    try:
        message = _service(request).apply_approved_update(body.approved)
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except (UpdateRefused, UpdateFailed) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"ok": True, "detail": message}


@router.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request):
    from fastapi.responses import StreamingResponse

    _task_or_404(task_id)
    service = _service(request)

    async def stream():
        import asyncio
        import json

        previous = ""
        for _ in range(40):
            task = service.get(task_id)
            if task is None:
                break
            payload = {
                "status": task["status"],
                "phase": task["phase"],
                "elapsed_seconds": task["elapsed_seconds"],
                "summary": task["summary"],
            }
            encoded = json.dumps(payload)
            if encoded != previous:
                yield f"data: {encoded}\n\n"
                previous = encoded
            if task["status"] not in {"queued", "running", "paused", "needs_approval"}:
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/api/voice/transcribe")
async def transcribe(request: Request) -> dict:
    data = await request.body()
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="That recording was too long. You can still type.")
    mime = (request.headers.get("content-type") or "audio/webm").split(";", 1)[0].strip().lower()
    if mime not in {
        "audio/webm",
        "audio/wav",
        "audio/mp3",
        "audio/mpeg",
        "audio/ogg",
        "audio/flac",
        "audio/aac",
        "audio/mp4",
    }:
        mime = "audio/webm"
    try:
        text = transcribe_audio(
            data,
            api_key=request.app.state.settings.gemini_api_key,
            mime=mime,
        )
    except VoiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return {"text": text}


@router.post("/api/tasks/{task_id}/resume")
def resume_task(task_id: str, request: Request) -> dict:
    _task_or_404(task_id)
    record = _service(request).resume(task_id)
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
