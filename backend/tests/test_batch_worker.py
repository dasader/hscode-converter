# backend/tests/test_batch_worker.py
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.data.batch_db import BatchDB
from app.services.batch_worker import BatchWorker


@pytest.fixture
def db(tmp_path):
    return BatchDB(str(tmp_path / "test.db"))


@pytest.fixture
def mock_pipeline():
    pipeline = MagicMock()
    pipeline.classify = AsyncMock(return_value=MagicMock(
        keywords=["키워드1", "키워드2"],
        results=[{"code": "8507601000", "confidence": 0.95, "reason": "사유"}],
        processing_time_ms=1000,
    ))
    return pipeline


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.sqlite_db_path = ":memory:"
    return settings


@pytest.mark.asyncio
async def test_worker_processes_item(db, mock_pipeline, mock_settings):
    job_id = db.create_job("test.xlsx", 1, 5, None, "chatgpt-5.4-mini")
    db.create_items(job_id, [{"row_index": 1, "task_name": None, "description": "테스트 기술 설명입니다 충분히 긴 텍스트"}])
    items = db.get_items(job_id)

    worker = BatchWorker(db=db, pipeline=mock_pipeline, settings=mock_settings, num_workers=1, rate_limiter=None)
    await worker.enqueue_items([items[0]])
    await worker.start()
    await asyncio.wait_for(worker.queue.join(), timeout=5)
    await worker.stop()

    updated = db.get_item(items[0]["item_id"])
    assert updated["status"] == "completed"
    result = json.loads(updated["result_json"])
    assert len(result["results"]) > 0


@pytest.mark.asyncio
async def test_worker_handles_failure(db, mock_settings):
    pipeline = MagicMock()
    pipeline.classify = AsyncMock(side_effect=Exception("API Error"))

    job_id = db.create_job("test.xlsx", 1, 5, None, "chatgpt-5.4-mini")
    db.create_items(job_id, [{"row_index": 1, "task_name": None, "description": "테스트 기술 설명입니다 충분히 긴 텍스트"}])
    items = db.get_items(job_id)

    worker = BatchWorker(db=db, pipeline=pipeline, settings=mock_settings, num_workers=1, rate_limiter=None)
    await worker.enqueue_items([items[0]])
    await worker.start()
    await asyncio.wait_for(worker.queue.join(), timeout=5)
    await worker.stop()

    updated = db.get_item(items[0]["item_id"])
    assert updated["status"] == "failed"
    assert "API Error" in updated["error_message"]
