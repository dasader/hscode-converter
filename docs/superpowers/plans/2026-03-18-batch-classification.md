# Batch Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 엑셀 파일로 R&D 기술 설명을 일괄 업로드하여 HSK 코드를 배치 매핑하고, 결과를 엑셀로 다운로드하는 비동기 배치 처리 기능 구현

**Architecture:** asyncio.Queue + Worker 10개로 병렬 처리, Token Bucket 이중 버킷(RPM 400/TPM 400K)으로 OpenAI rate limit 제어, SQLite WAL 모드로 동시 쓰기 안전성 확보, SSE로 실시간 진행률 전송

**Tech Stack:** FastAPI, asyncio, OpenAI AsyncClient, ChromaDB, SQLite(WAL), openpyxl, sse-starlette, React, TypeScript, Axios

**Spec:** `docs/superpowers/specs/2026-03-18-batch-classification-design.md`

---

## File Structure

### Backend 신규 파일

| 파일 | 역할 |
|------|------|
| `backend/app/services/rate_limiter.py` | Token Bucket 이중 버킷 (RPM/TPM) |
| `backend/app/data/batch_db.py` | batch_jobs, batch_items 테이블 CRUD |
| `backend/app/services/batch_service.py` | 엑셀 파싱, 작업 생성, 결과 엑셀 생성 |
| `backend/app/services/batch_worker.py` | asyncio.Queue Worker, 파이프라인 호출 |
| `backend/app/api/batch_routes.py` | 배치 전용 엔드포인트 6개 |
| `backend/tests/test_rate_limiter.py` | rate limiter 테스트 |
| `backend/tests/test_batch_db.py` | batch DB 테스트 |
| `backend/tests/test_batch_service.py` | batch service 테스트 |
| `backend/tests/test_batch_worker.py` | batch worker 테스트 |
| `backend/tests/test_batch_routes.py` | batch routes 통합 테스트 |

### Backend 수정 파일

| 파일 | 변경 |
|------|------|
| `backend/app/services/vector_search.py` | AsyncOpenAI + async search() + to_thread |
| `backend/app/core/pipeline.py` | search() await, rate_limiter 파라미터 |
| `backend/app/api/routes.py` | 파이프라인 싱글턴 패턴 |
| `backend/app/main.py` | batch_routes 등록, Worker 기동, 미완료 복원 |

### Frontend 신규 파일

| 파일 | 역할 |
|------|------|
| `frontend/src/components/BatchTab.tsx` | 배치 탭 UI 전체 |
| `frontend/src/components/BatchTab.css` | 배치 탭 스타일 |

### Frontend 수정 파일

| 파일 | 변경 |
|------|------|
| `frontend/src/api/types.ts` | 배치 관련 타입 추가 |
| `frontend/src/api/client.ts` | 배치 API 함수 추가 |
| `frontend/src/pages/ClassifyPage.tsx` | 탭 UI (단건/배치) 추가 |
| `frontend/src/pages/ClassifyPage.css` | 탭 스타일 추가 |

### 인프라 수정

| 파일 | 변경 |
|------|------|
| `frontend/nginx.conf` | SSE용 proxy_buffering off 추가 |

---

## Task 1: Token Bucket Rate Limiter

**Files:**
- Create: `backend/app/services/rate_limiter.py`
- Test: `backend/tests/test_rate_limiter.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_rate_limiter.py
import asyncio
import time
import pytest
from app.services.rate_limiter import TokenBucket, TokenBucketLimiter


@pytest.mark.asyncio
async def test_token_bucket_consume_success():
    """버킷에 토큰이 충분하면 즉시 소비"""
    bucket = TokenBucket(capacity=10, refill_rate=10)
    assert await bucket.consume(5) is True


@pytest.mark.asyncio
async def test_token_bucket_consume_insufficient():
    """토큰 부족 시 False 반환"""
    bucket = TokenBucket(capacity=2, refill_rate=1)
    await bucket.consume(2)
    assert await bucket.consume(1) is False


@pytest.mark.asyncio
async def test_token_bucket_refill():
    """시간 경과 후 토큰 보충"""
    bucket = TokenBucket(capacity=10, refill_rate=100)  # 초당 100개 리필
    await bucket.consume(10)
    await asyncio.sleep(0.15)  # 15개 리필 예상
    assert await bucket.consume(10) is True


@pytest.mark.asyncio
async def test_token_bucket_return_tokens():
    """토큰 반환 (정산)"""
    bucket = TokenBucket(capacity=10, refill_rate=0)
    await bucket.consume(8)
    await bucket.return_tokens(5)
    assert await bucket.consume(7) is True


@pytest.mark.asyncio
async def test_limiter_acquire_waits():
    """RPM/TPM 부족 시 대기 후 소비"""
    limiter = TokenBucketLimiter(rpm=5, tpm=100000, rpm_safety=1.0, tpm_safety=1.0)
    for _ in range(5):
        await limiter.acquire(rpm=1, tpm=10)
    start = time.monotonic()
    await limiter.acquire(rpm=1, tpm=10)
    elapsed = time.monotonic() - start
    assert elapsed > 0.05  # 리필 대기 발생


@pytest.mark.asyncio
async def test_limiter_settle():
    """정산: 예상 토큰과 실제 차이를 반환"""
    limiter = TokenBucketLimiter(rpm=100, tpm=100000, rpm_safety=1.0, tpm_safety=1.0)
    await limiter.acquire(rpm=1, tpm=1500)
    await limiter.settle(estimated_tpm=1500, actual_tpm=1000)
    # 500 토큰이 반환됨 — 정확한 내부 상태는 이후 acquire 성공으로 확인
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_rate_limiter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.rate_limiter'`

- [ ] **Step 3: Implement rate_limiter.py**

```python
# backend/app/services/rate_limiter.py
import asyncio
import time


class TokenBucket:
    def __init__(self, capacity: float, refill_rate: float):
        """
        Args:
            capacity: 버킷 최대 토큰 수
            refill_rate: 초당 리필 토큰 수
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    async def consume(self, amount: float) -> bool:
        async with self._lock:
            self._refill()
            if self.tokens >= amount:
                self.tokens -= amount
                return True
            return False

    async def return_tokens(self, amount: float):
        async with self._lock:
            self.tokens = min(self.capacity, self.tokens + amount)


class TokenBucketLimiter:
    def __init__(self, rpm: int = 500, tpm: int = 500000,
                 rpm_safety: float = 0.8, tpm_safety: float = 0.8):
        effective_rpm = rpm * rpm_safety
        effective_tpm = tpm * tpm_safety
        self.rpm_bucket = TokenBucket(
            capacity=effective_rpm,
            refill_rate=effective_rpm / 60.0,
        )
        self.tpm_bucket = TokenBucket(
            capacity=effective_tpm,
            refill_rate=effective_tpm / 60.0,
        )

    async def acquire(self, rpm: int = 1, tpm: int = 0):
        """RPM/TPM 토큰을 소비. 부족하면 리필될 때까지 대기."""
        while True:
            rpm_ok = await self.rpm_bucket.consume(rpm)
            if not rpm_ok:
                await asyncio.sleep(0.1)
                continue
            tpm_ok = await self.tpm_bucket.consume(tpm)
            if not tpm_ok:
                await self.rpm_bucket.return_tokens(rpm)
                await asyncio.sleep(0.1)
                continue
            return

    async def settle(self, estimated_tpm: int, actual_tpm: int):
        """실제 사용량과 예상치 차이를 정산"""
        diff = estimated_tpm - actual_tpm
        if diff > 0:
            await self.tpm_bucket.return_tokens(diff)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_rate_limiter.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rate_limiter.py backend/tests/test_rate_limiter.py
git commit -m "feat: add Token Bucket rate limiter for RPM/TPM control"
```

---

## Task 2: Batch DB Layer

**Files:**
- Create: `backend/app/data/batch_db.py`
- Test: `backend/tests/test_batch_db.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_batch_db.py
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
        top_n=5, confidence_threshold=None, model="chatgpt-5.4-mini"
    )
    job = db.get_job(job_id)
    assert job["status"] == "pending"
    assert job["total_items"] == 10
    assert job["top_n"] == 5


def test_create_items(db):
    job_id = db.create_job("test.xlsx", 2, 5, None, "chatgpt-5.4-mini")
    items = [
        {"row_index": 1, "task_name": "과제A", "description": "기술 설명 1"},
        {"row_index": 2, "task_name": None, "description": "기술 설명 2"},
    ]
    db.create_items(job_id, items)
    result = db.get_items(job_id)
    assert len(result) == 2
    assert result[0]["status"] == "pending"


def test_update_item_completed(db):
    job_id = db.create_job("test.xlsx", 1, 5, None, "chatgpt-5.4-mini")
    db.create_items(job_id, [{"row_index": 1, "task_name": None, "description": "desc"}])
    items = db.get_items(job_id)
    item_id = items[0]["item_id"]
    db.update_item_status(item_id, "completed", result_json='{"results": []}')
    updated = db.get_item(item_id)
    assert updated["status"] == "completed"
    assert updated["result_json"] == '{"results": []}'


def test_update_item_failed(db):
    job_id = db.create_job("test.xlsx", 1, 5, None, "chatgpt-5.4-mini")
    db.create_items(job_id, [{"row_index": 1, "task_name": None, "description": "desc"}])
    items = db.get_items(job_id)
    item_id = items[0]["item_id"]
    db.update_item_status(item_id, "failed", error_message="timeout")
    updated = db.get_item(item_id)
    assert updated["status"] == "failed"
    assert updated["retry_count"] == 1


def test_update_job_progress(db):
    job_id = db.create_job("test.xlsx", 2, 5, None, "chatgpt-5.4-mini")
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
    assert job["status"] == "completed"  # 모든 건 처리 완료


def test_get_pending_items(db):
    job_id = db.create_job("test.xlsx", 2, 5, None, "chatgpt-5.4-mini")
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
    job_id = db.create_job("test.xlsx", 1, 5, None, "chatgpt-5.4-mini")
    db.create_items(job_id, [{"row_index": 1, "task_name": None, "description": "desc"}])
    items = db.get_items(job_id)
    db.update_item_status(items[0]["item_id"], "failed", error_message="err")
    count = db.reset_failed_items(job_id)
    assert count == 1
    updated = db.get_item(items[0]["item_id"])
    assert updated["status"] == "pending"


def test_recover_processing_items(db):
    """서버 재시작 시 processing 상태 복원"""
    job_id = db.create_job("test.xlsx", 1, 5, None, "chatgpt-5.4-mini")
    db.create_items(job_id, [{"row_index": 1, "task_name": None, "description": "desc"}])
    items = db.get_items(job_id)
    # 수동으로 processing 상태로 변경 (시뮬레이션)
    db._execute("UPDATE batch_items SET status='processing' WHERE item_id=?", (items[0]["item_id"],))
    recovered = db.recover_incomplete_items()
    assert len(recovered) == 1
    assert recovered[0]["status"] == "pending"


def test_list_jobs(db):
    db.create_job("a.xlsx", 1, 5, None, "chatgpt-5.4-mini")
    db.create_job("b.xlsx", 2, 10, 0.7, "chatgpt-5.4")
    jobs = db.list_jobs()
    assert len(jobs) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_batch_db.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement batch_db.py**

```python
# backend/app/data/batch_db.py
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

MAX_RETRIES = 3


class BatchDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._write_lock = threading.Lock()
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _execute(self, sql: str, params: tuple = ()):
        conn = self._connect()
        conn.execute(sql, params)
        conn.commit()
        conn.close()

    def _init_tables(self):
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS batch_jobs (
                job_id TEXT PRIMARY KEY,
                file_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                total_items INTEGER NOT NULL,
                completed_items INTEGER DEFAULT 0,
                failed_items INTEGER DEFAULT 0,
                top_n INTEGER DEFAULT 5,
                confidence_threshold REAL,
                model TEXT DEFAULT 'chatgpt-5.4-mini',
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS batch_items (
                item_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES batch_jobs(job_id),
                row_index INTEGER NOT NULL,
                task_name TEXT,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                result_json TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_batch_items_job_id ON batch_items(job_id);
            CREATE INDEX IF NOT EXISTS idx_batch_items_status ON batch_items(status);
        """)
        conn.close()

    def create_job(self, file_name: str, total_items: int, top_n: int,
                   confidence_threshold: float | None, model: str) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._write_lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO batch_jobs (job_id, file_name, total_items, top_n, confidence_threshold, model, created_at) VALUES (?,?,?,?,?,?,?)",
                (job_id, file_name, total_items, top_n, confidence_threshold, model, now),
            )
            conn.commit()
            conn.close()
        return job_id

    def create_items(self, job_id: str, items: list[dict]):
        now = datetime.now(timezone.utc).isoformat()
        with self._write_lock:
            conn = self._connect()
            for item in items:
                item_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO batch_items (item_id, job_id, row_index, task_name, description, created_at) VALUES (?,?,?,?,?,?)",
                    (item_id, job_id, item["row_index"], item.get("task_name"), item["description"], now),
                )
            conn.commit()
            conn.close()

    def get_job(self, job_id: str) -> dict | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM batch_jobs WHERE job_id=?", (job_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_item(self, item_id: str) -> dict | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM batch_items WHERE item_id=?", (item_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_items(self, job_id: str) -> list[dict]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM batch_items WHERE job_id=? ORDER BY row_index", (job_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_pending_items(self, job_id: str) -> list[dict]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM batch_items WHERE job_id=? AND status='pending' ORDER BY row_index", (job_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_item_status(self, item_id: str, status: str,
                           result_json: str | None = None,
                           error_message: str | None = None):
        now = datetime.now(timezone.utc).isoformat()
        with self._write_lock:
            conn = self._connect()
            if status == "completed":
                conn.execute(
                    "UPDATE batch_items SET status=?, result_json=?, completed_at=? WHERE item_id=?",
                    (status, result_json, now, item_id),
                )
            elif status == "failed":
                conn.execute(
                    "UPDATE batch_items SET status=?, error_message=?, retry_count=retry_count+1 WHERE item_id=?",
                    (status, error_message, item_id),
                )
            else:
                conn.execute("UPDATE batch_items SET status=? WHERE item_id=?", (status, item_id))
            conn.commit()
            conn.close()

    def refresh_job_progress(self, job_id: str):
        with self._write_lock:
            conn = self._connect()
            completed = conn.execute("SELECT COUNT(*) FROM batch_items WHERE job_id=? AND status='completed'", (job_id,)).fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM batch_items WHERE job_id=? AND status='failed'", (job_id,)).fetchone()[0]
            total = conn.execute("SELECT total_items FROM batch_jobs WHERE job_id=?", (job_id,)).fetchone()[0]
            new_status = "completed" if (completed + failed) >= total else "processing"
            now = datetime.now(timezone.utc).isoformat() if new_status == "completed" else None
            conn.execute(
                "UPDATE batch_jobs SET completed_items=?, failed_items=?, status=?, completed_at=COALESCE(?, completed_at) WHERE job_id=?",
                (completed, failed, new_status, now, job_id),
            )
            conn.commit()
            conn.close()

    def reset_failed_items(self, job_id: str) -> int:
        with self._write_lock:
            conn = self._connect()
            cursor = conn.execute(
                "UPDATE batch_items SET status='pending', error_message=NULL WHERE job_id=? AND status='failed' AND retry_count<?",
                (job_id, MAX_RETRIES),
            )
            count = cursor.rowcount
            if count > 0:
                conn.execute("UPDATE batch_jobs SET status='processing' WHERE job_id=?", (job_id,))
            conn.commit()
            conn.close()
        return count

    def recover_incomplete_items(self) -> list[dict]:
        """서버 재시작 시 processing 상태 항목을 pending으로 복구, max_retries 초과는 failed로"""
        with self._write_lock:
            conn = self._connect()
            conn.execute(
                f"UPDATE batch_items SET status='failed', error_message='서버 재시작으로 인한 실패' WHERE status='processing' AND retry_count>={MAX_RETRIES}"
            )
            conn.execute("UPDATE batch_items SET status='pending' WHERE status='processing'")
            conn.commit()
            rows = conn.execute("SELECT * FROM batch_items WHERE status='pending' ORDER BY row_index").fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def list_jobs(self) -> list[dict]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM batch_jobs ORDER BY created_at DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_batch_db.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/batch_db.py backend/tests/test_batch_db.py
git commit -m "feat: add batch DB layer with WAL mode and job/item CRUD"
```

---

## Task 3: VectorSearchService Async 전환

**Files:**
- Modify: `backend/app/services/vector_search.py`
- Modify: `backend/app/core/pipeline.py`

- [ ] **Step 1: Run existing tests to confirm current state**

Run: `cd backend && python -m pytest -v`
Expected: All existing tests PASS (baseline)

- [ ] **Step 2: Convert VectorSearchService to async**

`backend/app/services/vector_search.py` 전체를 아래로 교체:

```python
# backend/app/services/vector_search.py
import asyncio
from dataclasses import dataclass
import logging
from openai import AsyncOpenAI
import chromadb

logger = logging.getLogger(__name__)


@dataclass
class SearchCandidate:
    code: str
    name: str
    distance: float


class VectorSearchService:
    EMBEDDING_MODEL = "text-embedding-3-small"

    def __init__(self, openai_api_key: str, chroma_db_path: str):
        self.openai_client = AsyncOpenAI(api_key=openai_api_key)
        self.chroma_client = chromadb.PersistentClient(path=chroma_db_path)

    @staticmethod
    def deduplicate(candidates: list[SearchCandidate]) -> list[SearchCandidate]:
        best: dict[str, SearchCandidate] = {}
        for c in candidates:
            if c.code not in best or c.distance < best[c.code].distance:
                best[c.code] = c
        return sorted(best.values(), key=lambda x: x.distance)

    @staticmethod
    def filter_by_threshold(candidates: list[SearchCandidate], threshold: float) -> list[SearchCandidate]:
        return [c for c in candidates if c.distance <= threshold]

    async def search(self, keywords: list[str], limit: int = 50, threshold: float = 0.3,
                     rate_limiter=None) -> list[SearchCandidate]:
        collection = await asyncio.to_thread(self.chroma_client.get_collection, "hsk_codes")
        all_candidates: list[SearchCandidate] = []
        for keyword in keywords:
            if rate_limiter:
                await rate_limiter.acquire(rpm=1, tpm=10)
            embedding = await self._get_embedding(keyword)
            results = await asyncio.to_thread(
                collection.query, query_embeddings=[embedding],
                n_results=min(limit, 50), include=["documents", "distances", "metadatas"],
            )
            if results["ids"] and results["ids"][0]:
                for code, doc, dist in zip(results["ids"][0], results["documents"][0], results["distances"][0]):
                    all_candidates.append(SearchCandidate(code=code, name=doc, distance=dist))
        deduped = self.deduplicate(all_candidates)
        filtered = self.filter_by_threshold(deduped, threshold)
        result = filtered[:limit]
        logger.info(f"벡터 검색 완료: {len(keywords)}개 키워드 → {len(result)}개 후보")
        return result

    async def _get_embedding(self, text: str) -> list[float]:
        response = await self.openai_client.embeddings.create(model=self.EMBEDDING_MODEL, input=[text])
        return response.data[0].embedding
```

- [ ] **Step 3: Update existing test_pipeline.py for async search**

기존 `backend/tests/test_pipeline.py`에서 `vector_search.search`가 `MagicMock`이면 `await`에 실패하므로, `AsyncMock`으로 변경 필요:

```python
# 기존: mock_search.search.return_value = [...]
# 변경:
from unittest.mock import AsyncMock
mock_search = MagicMock()
mock_search.search = AsyncMock(return_value=[SearchCandidate(...)])
```

- [ ] **Step 4: Update pipeline.py to await search() and add rate_limiter**

`backend/app/core/pipeline.py` 전체를 아래로 교체:

```python
# backend/app/core/pipeline.py
import asyncio
import time
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable
from app.services.keyword_extractor import KeywordExtractor
from app.services.vector_search import VectorSearchService
from app.services.reranker import Reranker

logger = logging.getLogger(__name__)


class PipelineStep(Enum):
    KEYWORD_EXTRACTION = "keyword_extraction"
    VECTOR_SEARCH = "vector_search"
    RERANKING = "reranking"


@dataclass
class PipelineResult:
    keywords: list[str]
    results: list[dict]
    processing_time_ms: int = 0


class ClassificationPipeline:
    def __init__(self, keyword_extractor: KeywordExtractor, vector_search: VectorSearchService, reranker: Reranker,
                 vector_search_limit: int = 50, similarity_threshold: float = 0.3, pipeline_timeout: int = 30):
        self.keyword_extractor = keyword_extractor
        self.vector_search = vector_search
        self.reranker = reranker
        self.vector_search_limit = vector_search_limit
        self.similarity_threshold = similarity_threshold
        self.pipeline_timeout = pipeline_timeout

    async def classify(self, description: str, top_n: int = 5, model: str = "chatgpt-5.4-mini",
                       on_step: Callable[[PipelineStep], None] | None = None,
                       rate_limiter=None) -> PipelineResult:
        return await asyncio.wait_for(
            self._classify_impl(description, top_n, model, on_step, rate_limiter),
            timeout=self.pipeline_timeout,
        )

    async def _classify_impl(self, description: str, top_n: int = 5, model: str = "chatgpt-5.4-mini",
                              on_step: Callable[[PipelineStep], None] | None = None,
                              rate_limiter=None) -> PipelineResult:
        start = time.time()
        if on_step:
            on_step(PipelineStep.KEYWORD_EXTRACTION)
        if rate_limiter:
            await rate_limiter.acquire(rpm=1, tpm=470)
        keywords = await self.keyword_extractor.extract(description, model=model)

        if on_step:
            on_step(PipelineStep.VECTOR_SEARCH)
        candidates = await self.vector_search.search(
            keywords, limit=self.vector_search_limit,
            threshold=self.similarity_threshold, rate_limiter=rate_limiter,
        )

        if on_step:
            on_step(PipelineStep.RERANKING)
        if rate_limiter:
            await rate_limiter.acquire(rpm=1, tpm=950)
        results = await self.reranker.rerank(description, candidates, top_n, model=model)

        elapsed_ms = int((time.time() - start) * 1000)
        logger.info(f"파이프라인 완료: {elapsed_ms}ms")
        return PipelineResult(keywords=keywords, results=results, processing_time_ms=elapsed_ms)
```

- [ ] **Step 5: Run all tests**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS (기존 + 신규)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/vector_search.py backend/app/core/pipeline.py backend/tests/test_pipeline.py
git commit -m "refactor: convert VectorSearchService to async with rate_limiter support"
```

---

## Task 4: Pipeline Singleton & routes.py 리팩터링

**Files:**
- Modify: `backend/app/api/routes.py`

- [ ] **Step 1: Refactor get_pipeline to singleton**

`backend/app/api/routes.py`에서 `get_pipeline()`을 싱글턴으로 변경:

```python
# backend/app/api/routes.py — 상단에 싱글턴 추가
_pipeline_instance: ClassificationPipeline | None = None


def get_pipeline(settings: Settings | None = None) -> ClassificationPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        if settings is None:
            settings = get_settings()
        _pipeline_instance = ClassificationPipeline(
            keyword_extractor=KeywordExtractor(settings.openai_api_key),
            vector_search=VectorSearchService(settings.openai_api_key, settings.chroma_db_path),
            reranker=Reranker(settings.openai_api_key),
            vector_search_limit=settings.vector_search_limit,
            similarity_threshold=settings.similarity_threshold,
            pipeline_timeout=settings.pipeline_timeout,
        )
    return _pipeline_instance
```

기존 `classify` 엔드포인트에서 `settings` 인자 제거:

```python
@router.post("/classify", response_model=ClassifyResponse)
async def classify(request: ClassifyRequest):
    settings = get_settings()
    pipeline = get_pipeline(settings)
    # ... 나머지 동일
```

- [ ] **Step 2: Run existing tests**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/routes.py
git commit -m "refactor: convert pipeline to singleton pattern"
```

---

## Task 5: Batch Service (엑셀 파싱 & 결과 생성)

**Files:**
- Create: `backend/app/services/batch_service.py`
- Test: `backend/tests/test_batch_service.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_batch_service.py
import json
import pytest
from openpyxl import Workbook
from app.services.batch_service import BatchService
from app.data.batch_db import BatchDB


@pytest.fixture
def db(tmp_path):
    return BatchDB(str(tmp_path / "test.db"))


@pytest.fixture
def service(db):
    return BatchService(db)


def _make_excel(tmp_path, rows):
    """테스트용 엑셀 생성"""
    wb = Workbook()
    ws = wb.active
    ws.append(["과제명", "기술설명"])
    for row in rows:
        ws.append(row)
    path = str(tmp_path / "test.xlsx")
    wb.save(path)
    return path


def test_parse_excel(tmp_path, service):
    path = _make_excel(tmp_path, [
        ["과제A", "리튬이온 배터리 양극재 제조 기술에 대한 설명입니다"],
        ["과제B", "수소연료전지 막전극접합체 제조를 위한 촉매 기술"],
        [None, ""],  # 빈 기술설명 — 건너뜀
        [None, "짧은"],  # 10자 미만 — 건너뜀
    ])
    items = service.parse_excel(path)
    assert len(items) == 2
    assert items[0]["task_name"] == "과제A"
    assert items[0]["row_index"] == 2


def test_parse_excel_max_rows(tmp_path, service):
    rows = [[f"과제{i}", f"기술 설명 번호 {i} 입니다. 이것은 충분히 긴 설명입니다."] for i in range(501)]
    path = _make_excel(tmp_path, rows)
    with pytest.raises(ValueError, match="500건"):
        service.parse_excel(path)


def test_create_template(tmp_path, service):
    path = str(tmp_path / "template.xlsx")
    service.create_template(path)
    from openpyxl import load_workbook
    wb = load_workbook(path)
    ws = wb.active
    assert ws.cell(1, 1).value == "과제명"
    assert ws.cell(1, 2).value == "기술설명"


def test_create_job_from_excel(tmp_path, db, service):
    path = _make_excel(tmp_path, [
        ["과제A", "리튬이온 배터리 양극재 제조 기술에 대한 설명입니다"],
    ])
    job_id = service.create_job(path, "test.xlsx", top_n=5, confidence_threshold=None, model="chatgpt-5.4-mini")
    job = db.get_job(job_id)
    assert job["total_items"] == 1
    items = db.get_items(job_id)
    assert len(items) == 1


def test_generate_result_excel_topn_mode(tmp_path, db, service):
    job_id = db.create_job("test.xlsx", 1, 5, None, "chatgpt-5.4-mini")
    db.create_items(job_id, [{"row_index": 2, "task_name": "과제A", "description": "기술 설명"}])
    items = db.get_items(job_id)
    result = {
        "results": [
            {"rank": 1, "hsk_code": "8507.60-1000", "name_kr": "리튬이온 축전지", "name_en": "Li-ion", "confidence": 0.95, "reason": "사유"},
            {"rank": 2, "hsk_code": "8507.50-0000", "name_kr": "니켈 축전지", "name_en": None, "confidence": 0.7, "reason": "사유2"},
        ],
        "keywords_extracted": ["양극재", "배터리"],
    }
    db.update_item_status(items[0]["item_id"], "completed", result_json=json.dumps(result, ensure_ascii=False))
    db.refresh_job_progress(job_id)

    output_path = str(tmp_path / "result.xlsx")
    service.generate_result_excel(job_id, output_path)

    from openpyxl import load_workbook
    wb = load_workbook(output_path)
    assert "요약" in wb.sheetnames
    assert "상세" in wb.sheetnames
    summary = wb["요약"]
    assert summary.cell(1, 5).value == "HSK코드_1"
    assert summary.cell(2, 5).value == "8507.60-1000"
    detail = wb["상세"]
    assert detail.cell(2, 4).value == "8507.60-1000"
    assert detail.cell(3, 4).value == "8507.50-0000"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_batch_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement batch_service.py**

```python
# backend/app/services/batch_service.py
import json
import logging
from openpyxl import Workbook, load_workbook
from app.data.batch_db import BatchDB

logger = logging.getLogger(__name__)

MAX_ROWS = 500
MIN_DESC_LENGTH = 10


class BatchService:
    def __init__(self, batch_db: BatchDB):
        self.db = batch_db

    def parse_excel(self, file_path: str) -> list[dict]:
        wb = load_workbook(file_path, read_only=True)
        ws = wb.active
        items = []
        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not row or len(row) < 2:
                continue
            task_name = str(row[0]).strip() if row[0] else None
            description = str(row[1]).strip() if row[1] else ""
            if len(description) < MIN_DESC_LENGTH:
                continue
            items.append({"row_index": row_idx, "task_name": task_name, "description": description})
        wb.close()
        if len(items) > MAX_ROWS:
            raise ValueError(f"최대 {MAX_ROWS}건까지 지원합니다. (입력: {len(items)}건)")
        return items

    def create_template(self, output_path: str):
        wb = Workbook()
        ws = wb.active
        ws.title = "입력"
        ws.append(["과제명", "기술설명"])
        ws.column_dimensions["A"].width = 30
        ws.column_dimensions["B"].width = 80
        wb.save(output_path)

    def create_job(self, file_path: str, file_name: str, top_n: int,
                   confidence_threshold: float | None, model: str) -> str:
        items = self.parse_excel(file_path)
        if not items:
            raise ValueError("유효한 기술 설명이 없습니다.")
        job_id = self.db.create_job(file_name, len(items), top_n, confidence_threshold, model)
        self.db.create_items(job_id, items)
        return job_id

    def generate_result_excel(self, job_id: str, output_path: str):
        job = self.db.get_job(job_id)
        items = self.db.get_items(job_id)
        top_n = job["top_n"]
        confidence_threshold = job["confidence_threshold"]

        wb = Workbook()

        # --- 요약 시트 ---
        ws_summary = wb.active
        ws_summary.title = "요약"

        # 결과 파싱하여 최대 코드 수 결정
        parsed_items = []
        max_codes = 0
        for item in items:
            result_data = json.loads(item["result_json"]) if item["result_json"] else None
            codes = []
            if result_data and item["status"] == "completed":
                results = result_data.get("results", [])
                if confidence_threshold is not None:
                    results = [r for r in results if r.get("confidence", 0) >= confidence_threshold]
                codes = [r["hsk_code"] for r in results]
            keywords = ", ".join(result_data.get("keywords_extracted", [])) if result_data else ""
            parsed_items.append({
                "item": item, "codes": codes, "keywords": keywords,
                "results": result_data.get("results", []) if result_data else [],
            })
            max_codes = max(max_codes, len(codes))

        if confidence_threshold is None:
            num_code_cols = top_n
        else:
            num_code_cols = min(max_codes, 20)

        # 헤더
        headers = ["과제명", "기술설명", "상태", "추출 키워드"]
        for i in range(1, num_code_cols + 1):
            headers.append(f"HSK코드_{i}")
        ws_summary.append(headers)

        # 데이터
        for p in parsed_items:
            row = [
                p["item"]["task_name"] or "",
                p["item"]["description"],
                "성공" if p["item"]["status"] == "completed" else "실패",
                p["keywords"],
            ]
            for i in range(num_code_cols):
                row.append(p["codes"][i] if i < len(p["codes"]) else "")
            ws_summary.append(row)

        # --- 상세 시트 ---
        ws_detail = wb.create_sheet("상세")
        ws_detail.append(["과제명", "기술설명", "순위", "HSK코드", "품목명(한)", "품목명(영)", "신뢰도(%)", "선정 사유"])

        for p in parsed_items:
            item = p["item"]
            if item["status"] == "completed" and p["results"]:
                results = p["results"]
                if confidence_threshold is not None:
                    results = [r for r in results if r.get("confidence", 0) >= confidence_threshold]
                for r in results:
                    ws_detail.append([
                        item["task_name"] or "",
                        item["description"],
                        r.get("rank", ""),
                        r.get("hsk_code", ""),
                        r.get("name_kr", ""),
                        r.get("name_en", ""),
                        round(r.get("confidence", 0) * 100, 1),
                        r.get("reason", ""),
                    ])
            elif item["status"] == "failed":
                ws_detail.append([
                    item["task_name"] or "",
                    item["description"],
                    "에러", "", "", "", "",
                    item.get("error_message", "알 수 없는 오류"),
                ])

        wb.save(output_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_batch_service.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/batch_service.py backend/tests/test_batch_service.py
git commit -m "feat: add BatchService for Excel parsing and result generation"
```

---

## Task 6: Batch Worker

**Files:**
- Create: `backend/app/services/batch_worker.py`
- Test: `backend/tests/test_batch_worker.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_batch_worker.py
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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
    # 큐가 빌 때까지 대기
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_batch_worker.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement batch_worker.py**

```python
# backend/app/services/batch_worker.py
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
    def __init__(self, db: BatchDB, pipeline, settings, num_workers: int = 10,
                 rate_limiter=None):
        self.db = db
        self.pipeline = pipeline
        self.settings = settings
        self.num_workers = num_workers
        self.rate_limiter = rate_limiter
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._workers: list[asyncio.Task] = []
        self._callbacks: dict[str, list] = {}  # job_id -> [callback_fn]

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
            await self.queue.put(None)  # poison pill
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

        # 신뢰도 모드면 top_n=20으로 최대 결과 확보
        effective_top_n = 20 if confidence_threshold is not None else top_n

        # 지수 백오프 재시도 (429, 500, 503, timeout)
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
                wait = 2 ** (attempt + 1)  # 2s, 4s, 8s
                logger.warning(f"Item {item_id} 재시도 {attempt + 1}/{MAX_RETRIES}: {e}, {wait}s 대기")
                await asyncio.sleep(wait)

        if pipeline_result is None:
            raise last_error or Exception("최대 재시도 초과")

        try:

            # 결과에 name_kr, name_en 보강
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

        # job progress 갱신
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_batch_worker.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/batch_worker.py backend/tests/test_batch_worker.py
git commit -m "feat: add BatchWorker with async queue processing and progress callbacks"
```

---

## Task 7: Batch Routes (API 엔드포인트)

**Files:**
- Create: `backend/app/api/batch_routes.py`
- Test: `backend/tests/test_batch_routes.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_batch_routes.py
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from openpyxl import Workbook

# 환경변수 설정 (Settings 검증 통과용)
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")


@pytest.fixture
def excel_file(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["과제명", "기술설명"])
    ws.append(["과제A", "리튬이온 배터리 양극재 제조를 위한 니켈 코발트 망간 합성 기술 설명"])
    path = str(tmp_path / "test.xlsx")
    wb.save(path)
    return path


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_template_download(client):
    """템플릿 다운로드 엔드포인트"""
    response = client.get("/api/v1/batch/template")
    assert response.status_code == 200
    assert "spreadsheet" in response.headers["content-type"]


def test_upload_no_file(client):
    """파일 없이 업로드 시 422"""
    response = client.post("/api/v1/batch/upload")
    assert response.status_code == 422


def test_jobs_list(client):
    """작업 목록 조회"""
    response = client.get("/api/v1/batch/jobs")
    assert response.status_code == 200
    assert "jobs" in response.json()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_batch_routes.py -v`
Expected: FAIL

- [ ] **Step 3: Implement batch_routes.py**

```python
# backend/app/api/batch_routes.py
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

# 글로벌 참조 (main.py에서 주입)
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
    model: str = Form(default="chatgpt-5.4-mini"),
):
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail=".xlsx 파일만 지원합니다")

    # 임시 파일에 저장
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    try:
        shutil.copyfileobj(file.file, tmp)
        tmp.close()

        # confidence_threshold가 있으면 신뢰도 모드 우선
        effective_top_n = top_n if confidence_threshold is None else 20

        job_id = _batch_service.create_job(
            tmp.name, file.filename, effective_top_n, confidence_threshold, model,
        )

        # 큐에 투입
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
            # 현재 상태 즉시 전송
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


```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_batch_routes.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/batch_routes.py backend/tests/test_batch_routes.py
git commit -m "feat: add batch API routes (upload, progress SSE, download, retry)"
```

---

## Task 8: main.py 통합 (Worker 기동, 라우트 등록)

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Update main.py**

`backend/app/main.py`에 배치 시스템 초기화 추가:

```python
# backend/app/main.py
import asyncio
import glob
import os
import sqlite3
import threading
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router, ensure_data_dirs, get_pipeline
from app.api.batch_routes import router as batch_router, init_batch
from app.core.config import Settings
from app.data.batch_db import BatchDB
from app.services.batch_service import BatchService
from app.services.batch_worker import BatchWorker
from app.services.rate_limiter import TokenBucketLimiter

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_data_ready = threading.Event()
_loading_status = {"state": "idle", "message": ""}

# 배치 시스템 글로벌 참조
_batch_worker: BatchWorker | None = None


def _db_has_data(db_path: str) -> bool:
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM hsk_codes").fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


def _chroma_has_data(chroma_path: str) -> bool:
    try:
        import chromadb
        client = chromadb.PersistentClient(path=chroma_path)
        collection = client.get_collection("hsk_codes")
        return collection.count() > 0
    except Exception:
        return False


def _auto_load_sync(settings: Settings) -> None:
    global _loading_status
    try:
        db_ok = _db_has_data(settings.sqlite_db_path)
        chroma_ok = _chroma_has_data(settings.chroma_db_path)

        if db_ok and chroma_ok:
            logger.info("HSK 데이터와 임베딩이 이미 존재합니다.")
            _loading_status = {"state": "ready", "message": "데이터 준비 완료"}
            _data_ready.set()
            return

        pattern = os.path.join(settings.excel_dir, "*.xlsx")
        xlsx_files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if not xlsx_files:
            logger.warning(f"자동 로드할 엑셀 파일이 없습니다. {settings.excel_dir}/ 폴더에 관세청 HS부호 엑셀 파일을 넣어주세요.")
            _loading_status = {"state": "no_data", "message": "엑셀 파일 없음. data/ 폴더에 파일을 넣어주세요."}
            return

        excel_path = xlsx_files[0]

        if not db_ok:
            _loading_status = {"state": "loading", "message": f"엑셀 로드 중: {os.path.basename(excel_path)}"}
            logger.info(f"HSK 데이터 로드 시작: {excel_path}")
            from app.data.crawler import HskCrawler
            crawler = HskCrawler()
            records = crawler.load_from_excel(excel_path)
            crawler.save_to_sqlite(records, settings.sqlite_db_path, source_file=excel_path)
            logger.info(f"SQLite 저장 완료: {len(records)}건")

        if not chroma_ok:
            _loading_status = {"state": "embedding", "message": "임베딩 생성 중 (수 분 소요)..."}
            logger.info("임베딩 생성 시작...")
            from app.data.embedder import HskEmbedder
            embedder = HskEmbedder(settings.openai_api_key, settings.chroma_db_path)
            embedder.embed_from_sqlite(settings.sqlite_db_path)
            logger.info("임베딩 생성 완료.")

        _loading_status = {"state": "ready", "message": "데이터 준비 완료"}
        _data_ready.set()

    except Exception as e:
        logger.error(f"자동 로드 실패: {e}", exc_info=True)
        _loading_status = {"state": "error", "message": str(e)}


def create_app() -> FastAPI:
    app = FastAPI(title="HSCode Connector", version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(router, prefix="/api/v1")
    app.include_router(batch_router, prefix="/api/v1")

    @app.on_event("startup")
    async def startup():
        global _batch_worker
        try:
            settings = Settings()
            ensure_data_dirs(settings)

            # 데이터 로드 (백그라운드)
            thread = threading.Thread(target=_auto_load_sync, args=(settings,), daemon=True)
            thread.start()

            # 배치 시스템 초기화
            batch_db_path = os.path.join(os.path.dirname(settings.sqlite_db_path), "batch.db")
            batch_db = BatchDB(batch_db_path)
            batch_service = BatchService(batch_db)
            rate_limiter = TokenBucketLimiter(rpm=500, tpm=500000)
            pipeline = get_pipeline(settings)
            _batch_worker = BatchWorker(
                db=batch_db, pipeline=pipeline, settings=settings,
                num_workers=10, rate_limiter=rate_limiter,
            )
            init_batch(batch_db, batch_service, _batch_worker)

            # Worker 시작
            await _batch_worker.start()

            # 미완료 작업 복원
            recovered = batch_db.recover_incomplete_items()
            if recovered:
                logger.info(f"미완료 배치 작업 {len(recovered)}건 복원")
                await _batch_worker.enqueue_items(recovered)

        except Exception as e:
            logger.error(f"시작 실패: {e}", exc_info=True)

    @app.on_event("shutdown")
    async def shutdown():
        if _batch_worker:
            await _batch_worker.stop()

    @app.get("/health")
    async def health():
        return {"status": "ok", "data": _loading_status}

    @app.get("/api/v1/data/status")
    async def data_status():
        return _loading_status

    return app


app = create_app()
```

- [ ] **Step 2: Run all tests**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: integrate batch system into main app (worker startup, route registration)"
```

---

## Task 9: Nginx SSE 설정

**Files:**
- Modify: `frontend/nginx.conf`

- [ ] **Step 1: Add SSE proxy settings**

`frontend/nginx.conf`에 배치 API용 SSE 설정 추가:

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location /api/v1/batch/ {
        proxy_pass http://backend:8000/api/v1/batch/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }

    location /api/ {
        proxy_pass http://backend:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/nginx.conf
git commit -m "feat: add SSE proxy settings for batch API in nginx"
```

---

## Task 10: Frontend 타입 & API 클라이언트

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add batch types**

`frontend/src/api/types.ts`에 배치 관련 타입 추가:

```typescript
// 기존 타입 유지하고 아래 추가

export interface BatchUploadResponse {
  job_id: string;
  total_items: number;
  status: string;
}

export interface BatchJob {
  job_id: string;
  file_name: string;
  status: string;
  total_items: number;
  completed_items: number;
  failed_items: number;
  top_n: number;
  confidence_threshold: number | null;
  model: string;
  created_at: string;
  completed_at: string | null;
}

export interface BatchProgressEvent {
  type: 'progress' | 'item_done' | 'complete' | 'heartbeat';
  completed?: number;
  failed?: number;
  total?: number;
  percent?: number;
  row_index?: number;
  status?: string;
  hsk_code_1?: string;
  confidence_1?: number;
  error?: string;
}
```

- [ ] **Step 2: Add batch API functions**

`frontend/src/api/client.ts`에 배치 API 함수 추가:

```typescript
// 기존 코드 유지하고 아래 추가
import type { BatchUploadResponse, BatchJob } from './types';

export async function downloadTemplate(): Promise<Blob> {
  const { data } = await api.get('/batch/template', { responseType: 'blob' });
  return data;
}

export async function uploadBatch(
  file: File,
  topN: number,
  confidenceThreshold: number | null,
  model: string,
): Promise<BatchUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('top_n', String(topN));
  if (confidenceThreshold !== null) {
    formData.append('confidence_threshold', String(confidenceThreshold / 100));
  }
  formData.append('model', model);
  const { data } = await api.post<BatchUploadResponse>('/batch/upload', formData);
  return data;
}

export function subscribeBatchProgress(jobId: string): EventSource {
  return new EventSource(`/api/v1/batch/${jobId}/progress`);
}

export async function downloadBatchResult(jobId: string): Promise<Blob> {
  const { data } = await api.get(`/batch/${jobId}/download`, { responseType: 'blob' });
  return data;
}

export async function retryBatchFailed(jobId: string): Promise<{ retried: number }> {
  const { data } = await api.post(`/batch/${jobId}/retry`);
  return data;
}

export async function listBatchJobs(): Promise<{ jobs: BatchJob[] }> {
  const { data } = await api.get('/batch/jobs');
  return data;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts
git commit -m "feat: add batch API types and client functions"
```

---

## Task 11: BatchTab 컴포넌트

**Files:**
- Create: `frontend/src/components/BatchTab.tsx`
- Create: `frontend/src/components/BatchTab.css`

- [ ] **Step 1: Create BatchTab.css**

```css
/* frontend/src/components/BatchTab.css */
.batch-tab {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.batch-config {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: flex-end;
}

.batch-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.batch-field label {
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
}

.filter-toggle {
  display: flex;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}

.filter-toggle button {
  padding: 8px 16px;
  border: none;
  background: white;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s;
}

.filter-toggle button.active {
  background: #3b82f6;
  color: white;
}

.batch-input {
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 14px;
  width: 80px;
}

.upload-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  padding: 40px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  background: #f8fafc;
}

.upload-zone:hover,
.upload-zone.dragover {
  border-color: #3b82f6;
  background: #eff6ff;
}

.upload-zone input {
  display: none;
}

.upload-icon {
  font-size: 40px;
  margin-bottom: 8px;
}

.upload-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 4px;
}

.upload-desc {
  font-size: 13px;
  color: #94a3b8;
}

.file-preview {
  background: #f1f5f9;
  border-radius: 8px;
  padding: 12px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.file-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.file-name {
  font-weight: 600;
  font-size: 14px;
}

.file-count {
  font-size: 13px;
  color: #64748b;
}

.remove-file {
  background: none;
  border: none;
  color: #ef4444;
  cursor: pointer;
  font-size: 18px;
}

.batch-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.template-btn {
  padding: 10px 20px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: white;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.15s;
}

.template-btn:hover {
  background: #f1f5f9;
}

.upload-btn {
  padding: 10px 24px;
  border: none;
  border-radius: 8px;
  background: #3b82f6;
  color: white;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  transition: all 0.15s;
}

.upload-btn:hover:not(:disabled) {
  background: #2563eb;
}

.upload-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.progress-section {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 24px;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.progress-title {
  font-size: 16px;
  font-weight: 600;
}

.progress-stats {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: #64748b;
}

.progress-stats .success { color: #22c55e; font-weight: 600; }
.progress-stats .fail { color: #ef4444; font-weight: 600; }

.progress-bar-container {
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 16px;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6);
  border-radius: 4px;
  transition: width 0.3s ease;
}

.progress-percent {
  text-align: center;
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 8px;
}

.progress-eta {
  text-align: center;
  font-size: 13px;
  color: #94a3b8;
}

.result-section {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 24px;
  text-align: center;
}

.result-summary {
  font-size: 16px;
  margin-bottom: 16px;
}

.result-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
}

.download-btn {
  padding: 10px 24px;
  border: none;
  border-radius: 8px;
  background: #22c55e;
  color: white;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}

.retry-btn {
  padding: 10px 24px;
  border: 1px solid #f59e0b;
  border-radius: 8px;
  background: white;
  color: #f59e0b;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}
```

- [ ] **Step 2: Create BatchTab.tsx**

```tsx
// frontend/src/components/BatchTab.tsx
import { useState, useRef, useEffect, useCallback } from 'react';
import {
  downloadTemplate, uploadBatch, subscribeBatchProgress,
  downloadBatchResult, retryBatchFailed,
} from '../api/client';
import type { BatchProgressEvent } from '../api/types';
import './BatchTab.css';

const MODEL_OPTIONS = [
  { value: 'chatgpt-5.4-nano', label: 'GPT-5.4 Nano (빠름)' },
  { value: 'chatgpt-5.4-mini', label: 'GPT-5.4 Mini (균형)' },
  { value: 'chatgpt-5.4',      label: 'GPT-5.4 (정확)' },
];

interface Props {
  isReady: boolean;
}

type FilterMode = 'topn' | 'confidence';
type Phase = 'idle' | 'uploading' | 'processing' | 'complete';

export default function BatchTab({ isReady }: Props) {
  const [filterMode, setFilterMode] = useState<FilterMode>('topn');
  const [topN, setTopN] = useState(5);
  const [confidenceValue, setConfidenceValue] = useState(70);
  const [model, setModel] = useState('chatgpt-5.4-mini');
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState({ completed: 0, failed: 0, total: 0, percent: 0 });
  const [error, setError] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [startTime, setStartTime] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const cleanupSSE = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  useEffect(() => () => cleanupSSE(), [cleanupSSE]);

  const handleTemplate = async () => {
    const blob = await downloadTemplate();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'HSCode_배치분류_템플릿.xlsx';
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleFileSelect = (selected: File | null) => {
    if (selected && selected.name.endsWith('.xlsx')) {
      setFile(selected);
      setError('');
    } else if (selected) {
      setError('.xlsx 파일만 지원합니다');
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setPhase('uploading');
    setError('');
    try {
      const threshold = filterMode === 'confidence' ? confidenceValue : null;
      const result = await uploadBatch(file, topN, threshold, model);
      setJobId(result.job_id);
      setProgress({ completed: 0, failed: 0, total: result.total_items, percent: 0 });
      setPhase('processing');
      setStartTime(Date.now());

      // SSE 연결
      cleanupSSE();
      const es = subscribeBatchProgress(result.job_id);
      eventSourceRef.current = es;

      es.onmessage = (event) => {
        const data: BatchProgressEvent = JSON.parse(event.data);
        if (data.type === 'progress') {
          setProgress({
            completed: data.completed ?? 0,
            failed: data.failed ?? 0,
            total: data.total ?? 0,
            percent: data.percent ?? 0,
          });
        } else if (data.type === 'complete') {
          setProgress({
            completed: data.completed ?? 0,
            failed: data.failed ?? 0,
            total: data.total ?? 0,
            percent: 100,
          });
          setPhase('complete');
          cleanupSSE();
        }
      };
      es.onerror = () => {
        // 자동 재연결 시도
      };
    } catch (e: any) {
      setError(e.response?.data?.detail || '업로드 중 오류가 발생했습니다');
      setPhase('idle');
    }
  };

  const handleDownload = async () => {
    if (!jobId) return;
    const blob = await downloadBatchResult(jobId);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${file?.name?.replace('.xlsx', '') || 'batch'}_결과.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleRetry = async () => {
    if (!jobId) return;
    await retryBatchFailed(jobId);
    setPhase('processing');
    setStartTime(Date.now());
    cleanupSSE();
    const es = subscribeBatchProgress(jobId);
    eventSourceRef.current = es;
    es.onmessage = (event) => {
      const data: BatchProgressEvent = JSON.parse(event.data);
      if (data.type === 'progress') {
        setProgress({
          completed: data.completed ?? 0, failed: data.failed ?? 0,
          total: data.total ?? 0, percent: data.percent ?? 0,
        });
      } else if (data.type === 'complete') {
        setProgress({ completed: data.completed ?? 0, failed: data.failed ?? 0, total: data.total ?? 0, percent: 100 });
        setPhase('complete');
        cleanupSSE();
      }
    };
  };

  const getETA = () => {
    if (!startTime || progress.percent <= 0) return '';
    const elapsed = (Date.now() - startTime) / 1000;
    const remaining = (elapsed / progress.percent) * (100 - progress.percent);
    if (remaining < 60) return `약 ${Math.ceil(remaining)}초 남음`;
    return `약 ${Math.ceil(remaining / 60)}분 남음`;
  };

  return (
    <div className="batch-tab">
      {/* 설정 */}
      <div className="batch-config">
        <div className="batch-field">
          <label>필터링 모드</label>
          <div className="filter-toggle">
            <button className={filterMode === 'topn' ? 'active' : ''} onClick={() => setFilterMode('topn')}>상위 N개</button>
            <button className={filterMode === 'confidence' ? 'active' : ''} onClick={() => setFilterMode('confidence')}>신뢰도 기준</button>
          </div>
        </div>
        <div className="batch-field">
          <label>{filterMode === 'topn' ? '결과 수' : '최소 신뢰도(%)'}</label>
          {filterMode === 'topn' ? (
            <input type="number" className="batch-input" min={1} max={20} value={topN} onChange={(e) => setTopN(Number(e.target.value))} />
          ) : (
            <input type="number" className="batch-input" min={0} max={100} step={5} value={confidenceValue} onChange={(e) => setConfidenceValue(Number(e.target.value))} />
          )}
        </div>
        <div className="batch-field">
          <label>모델</label>
          <select className="model-selector" value={model} onChange={(e) => setModel(e.target.value)}>
            {MODEL_OPTIONS.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
          </select>
        </div>
      </div>

      {/* 업로드 */}
      {phase === 'idle' && (
        <>
          {!file ? (
            <div
              className={`upload-zone ${dragOver ? 'dragover' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFileSelect(e.dataTransfer.files[0]); }}
            >
              <input ref={fileInputRef} type="file" accept=".xlsx" onChange={(e) => handleFileSelect(e.target.files?.[0] || null)} />
              <div className="upload-icon">+</div>
              <div className="upload-title">엑셀 파일을 드래그하거나 클릭하여 업로드</div>
              <div className="upload-desc">.xlsx 형식, 최대 500건</div>
            </div>
          ) : (
            <div className="file-preview">
              <div className="file-info">
                <span className="file-name">{file.name}</span>
                <span className="file-count">{(file.size / 1024).toFixed(1)} KB</span>
              </div>
              <button className="remove-file" onClick={() => setFile(null)}>x</button>
            </div>
          )}
          <div className="batch-actions">
            <button className="template-btn" onClick={handleTemplate}>템플릿 다운로드</button>
            <button className="upload-btn" onClick={handleUpload} disabled={!file || !isReady || phase !== 'idle'}>배치 분류 시작</button>
          </div>
        </>
      )}

      {/* 진행률 */}
      {(phase === 'uploading' || phase === 'processing') && (
        <div className="progress-section">
          <div className="progress-header">
            <span className="progress-title">{phase === 'uploading' ? '업로드 중...' : '처리 중...'}</span>
            <div className="progress-stats">
              <span className="success">성공 {progress.completed}</span>
              <span className="fail">실패 {progress.failed}</span>
              <span>/ 전체 {progress.total}</span>
            </div>
          </div>
          <div className="progress-percent">{progress.percent.toFixed(1)}%</div>
          <div className="progress-bar-container">
            <div className="progress-bar-fill" style={{ width: `${progress.percent}%` }} />
          </div>
          <div className="progress-eta">{getETA()}</div>
        </div>
      )}

      {/* 결과 */}
      {phase === 'complete' && (
        <div className="result-section">
          <div className="result-summary">
            처리 완료: <strong>{progress.completed}건</strong> 성공, <strong>{progress.failed}건</strong> 실패
          </div>
          <div className="result-actions">
            <button className="download-btn" onClick={handleDownload}>결과 엑셀 다운로드</button>
            {progress.failed > 0 && (
              <button className="retry-btn" onClick={handleRetry}>실패 건 재시도 ({progress.failed}건)</button>
            )}
          </div>
        </div>
      )}

      {error && <div className="error-msg">{error}</div>}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/BatchTab.tsx frontend/src/components/BatchTab.css
git commit -m "feat: add BatchTab component with upload, progress, and download UI"
```

---

## Task 12: ClassifyPage 탭 통합

**Files:**
- Modify: `frontend/src/pages/ClassifyPage.tsx`
- Modify: `frontend/src/pages/ClassifyPage.css`

- [ ] **Step 1: Add tab UI to ClassifyPage.tsx**

`ClassifyPage.tsx`에서 탭 전환 추가. `return` 문 내부의 `<div className="classify-page">` 바로 안에 hero-section 다음, status-banner 전에 탭 UI 삽입:

상단 import에 추가:
```tsx
import BatchTab from '../components/BatchTab';
```

상태 추가:
```tsx
const [activeTab, setActiveTab] = useState<'single' | 'batch'>('single');
```

hero-section과 status-banner 사이에 탭 삽입:
```tsx
{/* Tab selector */}
<div className="tab-selector">
  <button className={`tab-btn ${activeTab === 'single' ? 'active' : ''}`} onClick={() => setActiveTab('single')}>단건 분류</button>
  <button className={`tab-btn ${activeTab === 'batch' ? 'active' : ''}`} onClick={() => setActiveTab('batch')}>배치 분류</button>
</div>
```

기존 input-section, error, pipeline-indicator, results-section을 `activeTab === 'single'` 조건으로 감싸고, `activeTab === 'batch'`일 때 BatchTab 렌더링:

```tsx
{activeTab === 'single' ? (
  <>
    {/* 기존 input-section ~ results-section 전체 */}
  </>
) : (
  <BatchTab isReady={isReady} />
)}
```

- [ ] **Step 2: Add tab styles to ClassifyPage.css**

`ClassifyPage.css` 하단에 추가:
```css
.tab-selector {
  display: flex;
  gap: 0;
  background: #f1f5f9;
  border-radius: 10px;
  padding: 4px;
  margin-bottom: 20px;
  width: fit-content;
}

.tab-btn {
  padding: 10px 28px;
  border: none;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  color: #64748b;
  transition: all 0.2s;
}

.tab-btn.active {
  background: white;
  color: #1e293b;
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}
```

- [ ] **Step 3: Verify in browser**

Run: `cd frontend && npm run dev`
Expected: http://localhost:5180 에서 탭 전환이 동작하고, 배치 탭에서 템플릿 다운로드가 가능

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ClassifyPage.tsx frontend/src/pages/ClassifyPage.css
git commit -m "feat: add batch/single tab switching to ClassifyPage"
```

---

## Task 13: 통합 테스트 & 최종 검증

- [ ] **Step 1: Run all backend tests**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build 성공, 에러 없음

- [ ] **Step 3: Docker Compose 빌드**

Run: `docker-compose build`
Expected: 양쪽 서비스 빌드 성공

- [ ] **Step 4: Commit all remaining changes**

```bash
git add -A
git commit -m "feat: complete batch classification system with Excel upload/download"
```
