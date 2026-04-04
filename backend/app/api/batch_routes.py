import asyncio
import json
import logging
import os
import shutil
import tempfile
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from app.core.config import Settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/batch")

_batch_db = None
_batch_service = None
_batch_worker = None


def init_batch(batch_db, batch_service, batch_worker):
    global _batch_db, _batch_service, _batch_worker
    _batch_db = batch_db
    _batch_service = batch_service
    _batch_worker = batch_worker


@router.get("/jobs")
async def list_jobs():
    jobs = _batch_db.list_jobs()
    return {"jobs": jobs}


@router.get("/template")
async def download_template():
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp.close()
    _batch_service.create_template(tmp.name)
    return FileResponse(
        tmp.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="HSCode_배치분류_템플릿.xlsx",
        background=BackgroundTask(os.unlink, tmp.name),
    )


@router.post("/upload")
async def upload_batch(
    file: UploadFile = File(...),
    top_n: int = Form(default=5),
    confidence_threshold: float | None = Form(default=None),
):
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail=".xlsx 파일만 지원합니다")

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    try:
        shutil.copyfileobj(file.file, tmp)
        tmp.close()

        settings = Settings()
        effective_top_n = top_n if confidence_threshold is None else settings.max_top_n_with_threshold

        job_id = _batch_service.create_job(
            tmp.name, file.filename, effective_top_n, confidence_threshold,
        )

        items = _batch_db.get_pending_items(job_id)
        await _batch_worker.enqueue_items(items)

        job = _batch_db.get_job(job_id)
        return {"job_id": job_id, "total_items": job["total_items"], "status": job["status"]}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@router.get("/{job_id}/progress")
async def job_progress_sse(job_id: str):
    job = _batch_db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def callback(event):
            await queue.put(event)

        _batch_worker.register_progress_callback(job_id, callback)
        try:
            current_job = _batch_db.get_job(job_id)
            completed = current_job["completed_items"]
            failed = current_job["failed_items"]
            total = current_job["total_items"]
            initial = {
                "type": "progress", "completed": completed, "failed": failed,
                "total": total, "percent": round((completed + failed) / max(total, 1) * 100, 1),
            }
            yield f"data: {json.dumps(initial, ensure_ascii=False)}\n\n"

            if current_job["status"] == "completed":
                complete_event = {"type": "complete", "completed": completed, "failed": failed, "total": total}
                yield f"data: {json.dumps(complete_event, ensure_ascii=False)}\n\n"
                return

            heartbeat_interval = 15
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") == "complete":
                        return
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            _batch_worker.unregister_progress_callback(job_id, callback)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{job_id}/download")
async def download_result(job_id: str):
    job = _batch_db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail="아직 처리가 완료되지 않았습니다")

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp.close()
    _batch_service.generate_result_excel(job_id, tmp.name)

    original_name = os.path.splitext(job["file_name"])[0]
    return FileResponse(
        tmp.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"{original_name}_결과.xlsx",
        background=BackgroundTask(os.unlink, tmp.name),
    )


@router.post("/{job_id}/retry")
async def retry_failed(job_id: str):
    job = _batch_db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

    count = _batch_db.reset_failed_items(job_id)
    if count == 0:
        return {"message": "재시도할 실패 건이 없습니다", "retried": 0}

    items = _batch_db.get_pending_items(job_id)
    await _batch_worker.enqueue_items(items)
    return {"message": f"{count}건 재시도 시작", "retried": count}
