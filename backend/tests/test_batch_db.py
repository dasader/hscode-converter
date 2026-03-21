import os
import pytest
from app.data.batch_db import BatchDB


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test_batch.db")
    return BatchDB(db_path)


def test_create_job(db):
    job_id = db.create_job(
        file_name="test.xlsx", total_items=10,
        top_n=5, confidence_threshold=None
    )
    job = db.get_job(job_id)
    assert job["status"] == "pending"
    assert job["total_items"] == 10
    assert job["top_n"] == 5


def test_create_items(db):
    job_id = db.create_job("test.xlsx", 2, 5, None)
    items = [
        {"row_index": 1, "task_name": "과제A", "description": "기술 설명 1"},
        {"row_index": 2, "task_name": None, "description": "기술 설명 2"},
    ]
    db.create_items(job_id, items)
    result = db.get_items(job_id)
    assert len(result) == 2
    assert result[0]["status"] == "pending"


def test_update_item_completed(db):
    job_id = db.create_job("test.xlsx", 1, 5, None)
    db.create_items(job_id, [{"row_index": 1, "task_name": None, "description": "desc"}])
    items = db.get_items(job_id)
    item_id = items[0]["item_id"]
    db.update_item_status(item_id, "completed", result_json='{"results": []}')
    updated = db.get_item(item_id)
    assert updated["status"] == "completed"
    assert updated["result_json"] == '{"results": []}'


def test_update_item_failed(db):
    job_id = db.create_job("test.xlsx", 1, 5, None)
    db.create_items(job_id, [{"row_index": 1, "task_name": None, "description": "desc"}])
    items = db.get_items(job_id)
    item_id = items[0]["item_id"]
    db.update_item_status(item_id, "failed", error_message="timeout")
    updated = db.get_item(item_id)
    assert updated["status"] == "failed"
    assert updated["retry_count"] == 1


def test_update_job_progress(db):
    job_id = db.create_job("test.xlsx", 2, 5, None)
    db.create_items(job_id, [
        {"row_index": 1, "task_name": None, "description": "desc1"},
        {"row_index": 2, "task_name": None, "description": "desc2"},
    ])
    items = db.get_items(job_id)
    db.update_item_status(items[0]["item_id"], "completed", result_json="{}")
    db.update_item_status(items[1]["item_id"], "failed", error_message="err")
    db.refresh_job_progress(job_id)
    job = db.get_job(job_id)
    assert job["completed_items"] == 1
    assert job["failed_items"] == 1
    assert job["status"] == "completed"


def test_get_pending_items(db):
    job_id = db.create_job("test.xlsx", 2, 5, None)
    db.create_items(job_id, [
        {"row_index": 1, "task_name": None, "description": "desc1"},
        {"row_index": 2, "task_name": None, "description": "desc2"},
    ])
    items = db.get_items(job_id)
    db.update_item_status(items[0]["item_id"], "completed", result_json="{}")
    pending = db.get_pending_items(job_id)
    assert len(pending) == 1
    assert pending[0]["row_index"] == 2


def test_reset_failed_items(db):
    job_id = db.create_job("test.xlsx", 1, 5, None)
    db.create_items(job_id, [{"row_index": 1, "task_name": None, "description": "desc"}])
    items = db.get_items(job_id)
    db.update_item_status(items[0]["item_id"], "failed", error_message="err")
    count = db.reset_failed_items(job_id)
    assert count == 1
    updated = db.get_item(items[0]["item_id"])
    assert updated["status"] == "pending"


def test_recover_processing_items(db):
    job_id = db.create_job("test.xlsx", 1, 5, None)
    db.create_items(job_id, [{"row_index": 1, "task_name": None, "description": "desc"}])
    items = db.get_items(job_id)
    db._execute("UPDATE batch_items SET status='processing' WHERE item_id=?", (items[0]["item_id"],))
    recovered = db.recover_incomplete_items()
    assert len(recovered) == 1
    assert recovered[0]["status"] == "pending"


def test_list_jobs(db):
    db.create_job("a.xlsx", 1, 5, None)
    db.create_job("b.xlsx", 2, 10, 0.7)
    jobs = db.list_jobs()
    assert len(jobs) == 2
