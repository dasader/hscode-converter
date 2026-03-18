import asyncio
import json
import logging
import sqlite3
from openai import RateLimitError, InternalServerError, APIConnectionError
from app.data.batch_db import BatchDB
from app.data.crawler import HskCrawler

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRYABLE_ERRORS = (RateLimitError, InternalServerError, APIConnectionError, asyncio.TimeoutError)


class BatchWorker:
    def __init__(self, db: BatchDB, pipeline, settings, num_workers: int = 10, rate_limiter=None):
        self.db = db
        self.pipeline = pipeline
        self.settings = settings
        self.num_workers = num_workers
        self.rate_limiter = rate_limiter
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._workers: list[asyncio.Task] = []
        self._callbacks: dict[str, list] = {}

    def register_progress_callback(self, job_id: str, callback):
        self._callbacks.setdefault(job_id, []).append(callback)

    def unregister_progress_callback(self, job_id: str, callback):
        if job_id in self._callbacks:
            self._callbacks[job_id] = [cb for cb in self._callbacks[job_id] if cb is not callback]

    async def _notify_progress(self, job_id: str, event: dict):
        for callback in self._callbacks.get(job_id, []):
            try:
                await callback(event)
            except Exception:
                pass

    async def enqueue_items(self, items: list[dict]):
        for item in items:
            await self.queue.put(item)

    async def start(self):
        for i in range(self.num_workers):
            task = asyncio.create_task(self._worker_loop(i))
            self._workers.append(task)

    async def stop(self):
        for _ in self._workers:
            await self.queue.put(None)
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def _worker_loop(self, worker_id: int):
        while True:
            item = await self.queue.get()
            if item is None:
                self.queue.task_done()
                break
            try:
                await self._process_item(item)
            except Exception as e:
                logger.error(f"Worker {worker_id} 예외: {e}", exc_info=True)
            finally:
                self.queue.task_done()

    async def _process_item(self, item: dict):
        item_id = item["item_id"]
        job_id = item["job_id"]
        description = item["description"]

        self.db.update_item_status(item_id, "processing")

        job = self.db.get_job(job_id)
        if job["status"] == "pending":
            self.db._execute("UPDATE batch_jobs SET status='processing' WHERE job_id=? AND status='pending'", (job_id,))

        top_n = job["top_n"]
        model = job["model"]
        confidence_threshold = job.get("confidence_threshold")
        effective_top_n = 20 if confidence_threshold is not None else top_n

        # Exponential backoff retry for retryable errors
        pipeline_result = None
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                pipeline_result = await self.pipeline.classify(
                    description, top_n=effective_top_n, model=model,
                    rate_limiter=self.rate_limiter,
                )
                break
            except RETRYABLE_ERRORS as e:
                last_error = e
                wait = 2 ** (attempt + 1)
                logger.warning(f"Item {item_id} 재시도 {attempt + 1}/{MAX_RETRIES}: {e}, {wait}s 대기")
                await asyncio.sleep(wait)
            except Exception as e:
                last_error = e
                break

        if pipeline_result is None:
            error = last_error or Exception("최대 재시도 초과")
            error_msg = str(error)[:500]
            logger.warning(f"Item {item_id} 처리 실패 (재시도 불가): {error_msg}")
            self.db.update_item_status(item_id, "failed", error_message=error_msg)
            await self._notify_progress(job_id, {
                "type": "item_done", "row_index": item["row_index"],
                "status": "failed", "error": error_msg,
            })
            self.db.refresh_job_progress(job_id)
            job = self.db.get_job(job_id)
            await self._notify_progress(job_id, {
                "type": "progress",
                "completed": job["completed_items"],
                "failed": job["failed_items"],
                "total": job["total_items"],
                "percent": round((job["completed_items"] + job["failed_items"]) / job["total_items"] * 100, 1),
            })
            if job["status"] == "completed":
                await self._notify_progress(job_id, {
                    "type": "complete",
                    "completed": job["completed_items"],
                    "failed": job["failed_items"],
                    "total": job["total_items"],
                })
            return

        try:
            results_with_names = []
            try:
                conn = sqlite3.connect(self.settings.sqlite_db_path)
                cursor = conn.cursor()
                for i, r in enumerate(pipeline_result.results, 1):
                    code = r.get("code", "")
                    row = cursor.execute("SELECT name_kr, name_en FROM hsk_codes WHERE code=?", (code,)).fetchone()
                    results_with_names.append({
                        "rank": i,
                        "hsk_code": HskCrawler.format_code(code),
                        "name_kr": row[0] if row else code,
                        "name_en": row[1] if row else None,
                        "confidence": r.get("confidence", 0.0),
                        "reason": r.get("reason", ""),
                    })
                conn.close()
            except Exception:
                for i, r in enumerate(pipeline_result.results, 1):
                    results_with_names.append({
                        "rank": i, "hsk_code": HskCrawler.format_code(r.get("code", "")),
                        "name_kr": r.get("code", ""), "name_en": None,
                        "confidence": r.get("confidence", 0.0), "reason": r.get("reason", ""),
                    })

            result_data = {
                "results": results_with_names,
                "keywords_extracted": pipeline_result.keywords,
                "processing_time_ms": pipeline_result.processing_time_ms,
            }

            self.db.update_item_status(item_id, "completed", result_json=json.dumps(result_data, ensure_ascii=False))

            await self._notify_progress(job_id, {
                "type": "item_done", "row_index": item["row_index"],
                "status": "completed",
                "hsk_code_1": results_with_names[0]["hsk_code"] if results_with_names else "",
                "confidence_1": results_with_names[0]["confidence"] if results_with_names else 0,
            })

        except Exception as e:
            error_msg = str(e)[:500]
            logger.warning(f"Item {item_id} 처리 실패: {error_msg}")
            self.db.update_item_status(item_id, "failed", error_message=error_msg)

            await self._notify_progress(job_id, {
                "type": "item_done", "row_index": item["row_index"],
                "status": "failed", "error": error_msg,
            })

        self.db.refresh_job_progress(job_id)
        job = self.db.get_job(job_id)

        await self._notify_progress(job_id, {
            "type": "progress",
            "completed": job["completed_items"],
            "failed": job["failed_items"],
            "total": job["total_items"],
            "percent": round((job["completed_items"] + job["failed_items"]) / job["total_items"] * 100, 1),
        })

        if job["status"] == "completed":
            await self._notify_progress(job_id, {
                "type": "complete",
                "completed": job["completed_items"],
                "failed": job["failed_items"],
                "total": job["total_items"],
            })
