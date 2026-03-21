# OpenAI → Gemini 마이그레이션 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RAG 파이프라인의 LLM/임베딩 백엔드를 OpenAI에서 Google Gemini로 전면 교체

**Architecture:** google-genai SDK를 사용하여 키워드 추출/리랭킹(gemini-3-flash-preview)과 임베딩(gemini-embedding-001, 1536차원)을 처리. 모델명은 환경변수로 관리하며, 프론트엔드의 모델 선택 UI는 제거.

**Tech Stack:** google-genai, google-api-core, ChromaDB, FastAPI, React+TypeScript

**Spec:** `docs/superpowers/specs/2026-03-21-gemini-migration-design.md`

---

### Task 1: 의존성 및 설정 변경

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/.env.example`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: 테스트 수정 — config 환경변수 변경**

`backend/tests/test_config.py` 전체를 아래로 교체:

```python
import os
import pytest


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-test")
    from app.core.config import Settings
    settings = Settings()
    assert settings.google_api_key == "test-key"
    assert settings.admin_api_key == "admin-test"


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-test")
    from app.core.config import Settings
    settings = Settings()
    assert settings.chroma_db_path == "./data/chromadb"
    assert settings.sqlite_db_path == "./data/hsk.db"
    assert settings.max_input_length == 2000
    assert settings.max_top_n == 20
    assert settings.vector_search_limit == 50
    assert settings.similarity_threshold == 1.5
    assert settings.gemini_model == "gemini-3-flash-preview"
    assert settings.gemini_embedding_model == "gemini-embedding-001"
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: FAIL — `google_api_key` 필드가 아직 없음

- [ ] **Step 3: requirements.txt 변경**

`backend/requirements.txt`에서 `openai==1.58.1`을 `google-genai`로 교체:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
google-genai
chromadb==0.5.23
pydantic==2.10.4
pydantic-settings==2.7.1
httpx==0.28.1
openpyxl==3.1.5
python-multipart==0.0.20
sse-starlette==2.2.1
pytest==8.3.4
pytest-asyncio==0.25.0
```

- [ ] **Step 4: pip install**

Run: `cd backend && pip install -r requirements.txt`

- [ ] **Step 5: config.py 수정**

`backend/app/core/config.py` 전체를 아래로 교체:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_api_key: str
    admin_api_key: str
    gemini_model: str = "gemini-3-flash-preview"
    gemini_embedding_model: str = "gemini-embedding-001"
    chroma_db_path: str = "./data/chromadb"
    sqlite_db_path: str = "./data/hsk.db"
    max_input_length: int = 2000
    max_top_n: int = 20
    vector_search_limit: int = 50
    similarity_threshold: float = 1.5
    pipeline_timeout: int = 120
    excel_dir: str = "./data"

    model_config = {"env_file": ".env", "extra": "ignore"}
```

- [ ] **Step 6: .env.example 수정**

`backend/.env.example` 전체를 아래로 교체:

```
GOOGLE_API_KEY=your-google-api-key-here
ADMIN_API_KEY=your-admin-key-here
GEMINI_MODEL=gemini-3-flash-preview
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
CHROMA_DB_PATH=./data/chromadb
SQLITE_DB_PATH=./data/hsk.db
BACKEND_PORT=8011
```

- [ ] **Step 7: 테스트 실행 — 통과 확인**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: 커밋**

```bash
git add backend/requirements.txt backend/.env.example backend/app/core/config.py backend/tests/test_config.py
git commit -m "chore: switch from openai to google-genai SDK and update config"
```

---

### Task 2: KeywordExtractor Gemini 전환

**Files:**
- Modify: `backend/app/services/keyword_extractor.py`
- Test: `backend/tests/test_keyword_extractor.py` (변경 없음 — static 메서드 테스트만 있음)

- [ ] **Step 1: keyword_extractor.py 전환**

`backend/app/services/keyword_extractor.py` 전체를 아래로 교체:

```python
import json
import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 R&D 기술 설명에서 관련 무역 상품을 추출하는 전문가입니다.
사용자가 제공하는 기술 설명을 분석하여, 해당 기술과 관련된 제품, 물질, 부품, 장비를 한국어와 영어로 추출하세요.
직접 언급되지 않았더라도 해당 기술로 생산되거나 사용되는 파생 제품도 포함하세요.
결과는 JSON 배열 형식으로만 반환하세요. 예: ["양극재", "cathode material", "리튬이온 배터리"]"""


class KeywordExtractor:
    def __init__(self, api_key: str, model: str):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    @staticmethod
    def build_prompt(description: str) -> str:
        return f"다음 R&D 기술 설명에서 관련 제품, 물질, 부품, 장비를 한국어와 영어로 추출하세요:\n\n{description}"

    @staticmethod
    def parse_keywords(raw: str) -> list[str]:
        raw = raw.strip()
        try:
            keywords = json.loads(raw)
            if isinstance(keywords, list):
                return [k.strip() for k in keywords if isinstance(k, str) and k.strip()]
        except json.JSONDecodeError:
            pass
        keywords = [k.strip().strip('"').strip("'") for k in raw.replace("\n", ",").split(",")]
        return [k for k in keywords if k]

    async def extract(self, description: str, max_retries: int = 2) -> list[str]:
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=self.build_prompt(description),
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.2,
                        response_mime_type="application/json",
                    ),
                )
                raw = response.text or ""
                keywords = self.parse_keywords(raw)
                logger.info(f"키워드 추출 완료: {len(keywords)}개 — {keywords}")
                return keywords
            except Exception as e:
                last_error = e
                logger.warning(f"키워드 추출 재시도 {attempt + 1}/{max_retries + 1}: {e}")
        raise last_error
```

- [ ] **Step 2: 기존 테스트 실행 — static 메서드 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_keyword_extractor.py -v`
Expected: PASS (3 tests — build_prompt, parse_keywords, parse_keywords_handles_malformed)

- [ ] **Step 3: 커밋**

```bash
git add backend/app/services/keyword_extractor.py
git commit -m "refactor: migrate KeywordExtractor from OpenAI to Gemini"
```

---

### Task 3: Reranker Gemini 전환

**Files:**
- Modify: `backend/app/services/reranker.py`
- Test: `backend/tests/test_reranker.py` (변경 없음 — static 메서드 테스트만 있음)

- [ ] **Step 1: reranker.py 전환**

`backend/app/services/reranker.py` 전체를 아래로 교체:

```python
import json
import re
import logging
from google import genai
from google.genai import types
from app.services.vector_search import SearchCandidate

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 HS 코드 분류 전문가입니다.
사용자가 제공하는 R&D 기술 설명과 후보 HSK 코드 목록을 비교하여,
관련도가 높은 순서대로 코드를 선정하고 신뢰도 점수와 선정 사유를 제시하세요.

반드시 후보 목록에 있는 코드만 선택하세요. 새로운 코드를 만들지 마세요.

결과는 JSON 배열로만 반환하세요:
[{"code": "코드", "confidence": 0.0~1.0, "reason": "선정 사유"}, ...]"""


class Reranker:
    def __init__(self, api_key: str, model: str):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    @staticmethod
    def build_candidates_text(candidates: list[SearchCandidate]) -> str:
        lines = [f"- {c.code}: {c.name}" for c in candidates]
        return "\n".join(lines)

    @staticmethod
    def parse_response(raw: str) -> list[dict]:
        raw = raw.strip()
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
        if match:
            raw = match.group(1).strip()
        try:
            results = json.loads(raw)
            if isinstance(results, list):
                return results
        except json.JSONDecodeError:
            logger.warning(f"리랭킹 응답 JSON 파싱 실패: {raw[:200]}")
        return []

    async def rerank(self, description: str, candidates: list[SearchCandidate], top_n: int, max_retries: int = 2) -> list[dict]:
        candidates_text = self.build_candidates_text(candidates)
        user_prompt = f"## R&D 기술 설명\n{description}\n\n## 후보 HSK 코드 목록\n{candidates_text}\n\n위 기술 설명과 가장 관련 있는 HSK 코드를 최대 {top_n}개 선정하세요."
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.1,
                        response_mime_type="application/json",
                    ),
                )
                raw = response.text or ""
                results = self.parse_response(raw)
                logger.info(f"리랭킹 완료: {len(results)}개 선정")
                return results[:top_n]
            except Exception as e:
                last_error = e
                logger.warning(f"리랭킹 재시도 {attempt + 1}/{max_retries + 1}: {e}")
        raise last_error
```

- [ ] **Step 2: 테스트 실행 — 통과 확인**

Run: `cd backend && python -m pytest tests/test_reranker.py -v`
Expected: PASS (3 tests)

- [ ] **Step 3: 커밋**

```bash
git add backend/app/services/reranker.py
git commit -m "refactor: migrate Reranker from OpenAI to Gemini"
```

---

### Task 4: VectorSearchService 임베딩 전환

**Files:**
- Modify: `backend/app/services/vector_search.py`
- Test: `backend/tests/test_vector_search.py` (변경 없음 — static 메서드 테스트만 있음)

- [ ] **Step 1: vector_search.py 전환**

`backend/app/services/vector_search.py` 전체를 아래로 교체:

```python
import asyncio
from dataclasses import dataclass
import logging
from google import genai
from google.genai import types
import chromadb

logger = logging.getLogger(__name__)


@dataclass
class SearchCandidate:
    code: str
    name: str
    distance: float


class VectorSearchService:
    EMBEDDING_DIMENSIONALITY = 1536

    def __init__(self, api_key: str, chroma_db_path: str, embedding_model: str):
        self.client = genai.Client(api_key=api_key)
        self.embedding_model = embedding_model
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
                where={"level": 5},
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
        response = await self.client.aio.models.embed_content(
            model=self.embedding_model,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=self.EMBEDDING_DIMENSIONALITY),
        )
        return list(response.embeddings[0].values)
```

- [ ] **Step 2: 테스트 실행 — 통과 확인**

Run: `cd backend && python -m pytest tests/test_vector_search.py -v`
Expected: PASS (3 tests)

- [ ] **Step 3: 커밋**

```bash
git add backend/app/services/vector_search.py
git commit -m "refactor: migrate VectorSearchService embedding from OpenAI to Gemini"
```

---

### Task 5: HskEmbedder 전환

**Files:**
- Modify: `backend/app/data/embedder.py`
- Test: `backend/tests/test_embedder.py` (변경 없음 — static 메서드 테스트만 있음)

- [ ] **Step 1: embedder.py 전환**

`backend/app/data/embedder.py` 전체를 아래로 교체:

```python
import sqlite3
import logging
from typing import Iterator
from google import genai
from google.genai import types
import chromadb

logger = logging.getLogger(__name__)


class HskEmbedder:
    """SQLite의 HSK 코드를 임베딩하여 ChromaDB에 저장.

    full_name 컬럼을 임베딩 텍스트로 사용.
    예: "제85류 전기기기 > 축전지 > 리튬이온 축전지 > 반도체 제조용 [자본재 > 전기·전자기기 > 반도체]"
    """

    EMBEDDING_DIMENSIONALITY = 1536
    BATCH_SIZE = 100

    def __init__(self, api_key: str, chroma_db_path: str, embedding_model: str):
        self.client = genai.Client(api_key=api_key)
        self.embedding_model = embedding_model
        self.chroma_client = chromadb.PersistentClient(path=chroma_db_path)

    @staticmethod
    def build_embedding_text(name_kr: str, name_en: str | None, full_name: str | None = None) -> str:
        """임베딩용 텍스트 생성. full_name이 있으면 우선 사용."""
        if full_name and full_name.strip():
            return full_name.strip()
        if name_en:
            return f"{name_kr} ({name_en})"
        return name_kr

    @staticmethod
    def chunk_list(items: list, size: int) -> Iterator[list]:
        for i in range(0, len(items), size):
            yield items[i : i + size]

    def embed_from_sqlite(self, sqlite_db_path: str) -> None:
        conn = sqlite3.connect(sqlite_db_path)
        cursor = conn.cursor()

        # full_name 컬럼이 있는지 확인
        columns = [col[1] for col in cursor.execute("PRAGMA table_info(hsk_codes)").fetchall()]
        has_full_name = "full_name" in columns

        if has_full_name:
            rows = cursor.execute(
                "SELECT code, name_kr, name_en, level, parent_code, full_name FROM hsk_codes"
            ).fetchall()
        else:
            rows = cursor.execute(
                "SELECT code, name_kr, name_en, level, parent_code FROM hsk_codes"
            ).fetchall()
        conn.close()

        # 기존 컬렉션 삭제 후 재생성
        try:
            self.chroma_client.delete_collection("hsk_codes")
        except Exception:
            pass
        collection = self.chroma_client.create_collection(
            name="hsk_codes",
            metadata={"hnsw:space": "cosine"},
        )

        for batch in self.chunk_list(rows, self.BATCH_SIZE):
            if has_full_name:
                texts = [self.build_embedding_text(row[1], row[2], row[5]) for row in batch]
            else:
                texts = [self.build_embedding_text(row[1], row[2]) for row in batch]

            embeddings = self._get_embeddings(texts)
            collection.add(
                ids=[row[0] for row in batch],
                embeddings=embeddings,
                documents=texts,
                metadatas=[
                    {"code": row[0], "level": row[3], "parent_code": row[4] or ""}
                    for row in batch
                ],
            )
            logger.info(f"임베딩 배치 저장: {len(batch)}건")

        logger.info(f"ChromaDB 임베딩 완료: 총 {len(rows)}건")

    def _get_embeddings(self, texts: list[str]) -> list[list[float]]:
        response = self.client.models.embed_content(
            model=self.embedding_model,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=self.EMBEDDING_DIMENSIONALITY),
        )
        return [list(e.values) for e in response.embeddings]
```

- [ ] **Step 2: 테스트 실행 — 통과 확인**

Run: `cd backend && python -m pytest tests/test_embedder.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: 커밋**

```bash
git add backend/app/data/embedder.py
git commit -m "refactor: migrate HskEmbedder from OpenAI to Gemini"
```

---

### Task 6: Pipeline 및 BatchWorker model 파라미터 제거

**Files:**
- Modify: `backend/app/core/pipeline.py`
- Modify: `backend/app/services/batch_worker.py`
- Modify: `backend/app/data/batch_db.py`
- Modify: `backend/app/services/batch_service.py`
- Test: `backend/tests/test_pipeline.py`
- Test: `backend/tests/test_batch_worker.py`
- Test: `backend/tests/test_batch_db.py`
- Test: `backend/tests/test_batch_service.py`

- [ ] **Step 1: 테스트 수정 — pipeline, batch_worker**

`backend/tests/test_pipeline.py`에서 `classify()` 호출에서 `model` 제거 (이미 model 파라미터가 없으므로 변경 불필요 — 확인만).

`backend/tests/test_batch_worker.py` 전체를 아래로 교체:

```python
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
    job_id = db.create_job("test.xlsx", 1, 5, None)
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

    job_id = db.create_job("test.xlsx", 1, 5, None)
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

- [ ] **Step 2: test_batch_db.py 수정 — create_job()에서 model 인자 제거**

`backend/tests/test_batch_db.py`에서 모든 `create_job()` 호출의 마지막 `model` 인자를 제거:

```
line 15: db.create_job(file_name="test.xlsx", total_items=10, top_n=5, confidence_threshold=None, model="chatgpt-5.4-mini")
→ db.create_job(file_name="test.xlsx", total_items=10, top_n=5, confidence_threshold=None)

line 24: db.create_job("test.xlsx", 2, 5, None, "chatgpt-5.4-mini")
→ db.create_job("test.xlsx", 2, 5, None)

line 36: db.create_job("test.xlsx", 1, 5, None, "chatgpt-5.4-mini")
→ db.create_job("test.xlsx", 1, 5, None)

line 47: db.create_job("test.xlsx", 1, 5, None, "chatgpt-5.4-mini")
→ db.create_job("test.xlsx", 1, 5, None)

line 58: db.create_job("test.xlsx", 2, 5, None, "chatgpt-5.4-mini")
→ db.create_job("test.xlsx", 2, 5, None)

line 74: db.create_job("test.xlsx", 2, 5, None, "chatgpt-5.4-mini")
→ db.create_job("test.xlsx", 2, 5, None)

line 87: db.create_job("test.xlsx", 1, 5, None, "chatgpt-5.4-mini")
→ db.create_job("test.xlsx", 1, 5, None)

line 98: db.create_job("test.xlsx", 1, 5, None, "chatgpt-5.4-mini")
→ db.create_job("test.xlsx", 1, 5, None)

line 108: db.create_job("a.xlsx", 1, 5, None, "chatgpt-5.4-mini")
→ db.create_job("a.xlsx", 1, 5, None)

line 109: db.create_job("b.xlsx", 2, 10, 0.7, "chatgpt-5.4")
→ db.create_job("b.xlsx", 2, 10, 0.7)
```

- [ ] **Step 3: test_batch_service.py 수정 — create_job()에서 model 인자 제거**

`backend/tests/test_batch_service.py`에서:

기존 (line 63):
```python
    job_id = service.create_job(path, "test.xlsx", top_n=5, confidence_threshold=None, model="chatgpt-5.4-mini")
```
변경:
```python
    job_id = service.create_job(path, "test.xlsx", top_n=5, confidence_threshold=None)
```

기존 (line 71):
```python
    job_id = db.create_job("test.xlsx", 1, 5, None, "chatgpt-5.4-mini")
```
변경:
```python
    job_id = db.create_job("test.xlsx", 1, 5, None)
```

- [ ] **Step 4: 테스트 실행 — 실패 확인**

Run: `cd backend && python -m pytest tests/test_pipeline.py tests/test_batch_worker.py tests/test_batch_db.py tests/test_batch_service.py -v`
Expected: FAIL — `create_job()`에 model 파라미터가 아직 있음 (구현 코드 미수정)

- [ ] **Step 5: pipeline.py 수정 — model 파라미터 제거**

`backend/app/core/pipeline.py` 전체를 아래로 교체:

```python
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

    async def classify(self, description: str, top_n: int = 5,
                       on_step: Callable[[PipelineStep], None] | None = None,
                       rate_limiter=None) -> PipelineResult:
        return await asyncio.wait_for(
            self._classify_impl(description, top_n, on_step, rate_limiter),
            timeout=self.pipeline_timeout,
        )

    async def _classify_impl(self, description: str, top_n: int = 5,
                              on_step: Callable[[PipelineStep], None] | None = None,
                              rate_limiter=None) -> PipelineResult:
        start = time.time()
        if on_step:
            on_step(PipelineStep.KEYWORD_EXTRACTION)
        if rate_limiter:
            await rate_limiter.acquire(rpm=1, tpm=470)
        keywords = await self.keyword_extractor.extract(description)

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
        results = await self.reranker.rerank(description, candidates, top_n)

        elapsed_ms = int((time.time() - start) * 1000)
        logger.info(f"파이프라인 완료: {elapsed_ms}ms")
        return PipelineResult(keywords=keywords, results=results, processing_time_ms=elapsed_ms)
```

- [ ] **Step 6: batch_db.py 수정 — create_job에서 model 파라미터 제거**

`backend/app/data/batch_db.py`에서 `create_job` 메서드의 시그니처와 INSERT문 변경:

기존 (line 63):
```python
    def create_job(self, file_name, total_items, top_n, confidence_threshold, model):
```
변경:
```python
    def create_job(self, file_name, total_items, top_n, confidence_threshold):
```

기존 INSERT문 (line 68-70):
```python
            conn.execute(
                "INSERT INTO batch_jobs (job_id, file_name, total_items, top_n, confidence_threshold, model, created_at) VALUES (?,?,?,?,?,?,?)",
                (job_id, file_name, total_items, top_n, confidence_threshold, model, now),
```
변경:
```python
            conn.execute(
                "INSERT INTO batch_jobs (job_id, file_name, total_items, top_n, confidence_threshold, created_at) VALUES (?,?,?,?,?,?)",
                (job_id, file_name, total_items, top_n, confidence_threshold, now),
```

참고: 테이블 스키마의 `model TEXT DEFAULT 'chatgpt-5.4-mini'` 컬럼은 하위호환을 위해 유지.

- [ ] **Step 7: batch_service.py 수정 — create_job에서 model 파라미터 제거**

`backend/app/services/batch_service.py`에서:

기존 (line 42-43):
```python
    def create_job(self, file_path: str, file_name: str, top_n: int,
                   confidence_threshold: float | None, model: str) -> str:
```
변경:
```python
    def create_job(self, file_path: str, file_name: str, top_n: int,
                   confidence_threshold: float | None) -> str:
```

기존 (line 47):
```python
        job_id = self.db.create_job(file_name, len(items), top_n, confidence_threshold, model)
```
변경:
```python
        job_id = self.db.create_job(file_name, len(items), top_n, confidence_threshold)
```

- [ ] **Step 8: batch_worker.py 수정 — 에러 클래스 + model 참조 제거**

`backend/app/services/batch_worker.py`에서:

기존 import (line 5):
```python
from openai import RateLimitError, InternalServerError, APIConnectionError
```
변경:
```python
from google.api_core.exceptions import ResourceExhausted, InternalServerError, ServiceUnavailable
```

기존 (line 12):
```python
RETRYABLE_ERRORS = (RateLimitError, InternalServerError, APIConnectionError, asyncio.TimeoutError)
```
변경:
```python
RETRYABLE_ERRORS = (ResourceExhausted, InternalServerError, ServiceUnavailable, asyncio.TimeoutError)
```

기존 (line 79-83) — `_process_item` 내부:
```python
        top_n = job["top_n"]
        model = job["model"]
        confidence_threshold = job.get("confidence_threshold")
        effective_top_n = 20 if confidence_threshold is not None else top_n
```
변경:
```python
        top_n = job["top_n"]
        confidence_threshold = job.get("confidence_threshold")
        effective_top_n = 20 if confidence_threshold is not None else top_n
```

기존 (line 89-90):
```python
                pipeline_result = await self.pipeline.classify(
                    description, top_n=effective_top_n, model=model,
```
변경:
```python
                pipeline_result = await self.pipeline.classify(
                    description, top_n=effective_top_n,
```

- [ ] **Step 9: 테스트 실행 — 통과 확인**

Run: `cd backend && python -m pytest tests/test_pipeline.py tests/test_batch_worker.py tests/test_batch_db.py tests/test_batch_service.py -v`
Expected: PASS

- [ ] **Step 10: 커밋**

```bash
git add backend/app/core/pipeline.py backend/app/services/batch_worker.py backend/app/data/batch_db.py backend/app/services/batch_service.py backend/tests/test_pipeline.py backend/tests/test_batch_worker.py backend/tests/test_batch_db.py backend/tests/test_batch_service.py
git commit -m "refactor: remove model parameter from pipeline chain and batch system"
```

---

### Task 7: API 라우트 및 스키마 변경

**Files:**
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/api/batch_routes.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_batch_routes.py`
- Test: `backend/tests/test_routes.py`

- [ ] **Step 1: test_batch_routes.py 및 test_routes.py 수정**

`backend/tests/test_batch_routes.py` line 8:

기존:
```python
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key")
```
변경:
```python
os.environ.setdefault("GOOGLE_API_KEY", "test-dummy-key")
```

`backend/tests/test_routes.py` line 6:

기존:
```python
ENV_VARS = {"OPENAI_API_KEY": "test-key", "ADMIN_API_KEY": "test-admin"}
```
변경:
```python
ENV_VARS = {"GOOGLE_API_KEY": "test-key", "ADMIN_API_KEY": "test-admin"}
```

- [ ] **Step 2: schemas.py 수정 — model 필드 제거**

`backend/app/models/schemas.py`에서:

기존 (line 7):
```python
    model: str = Field(default="chatgpt-5.4-mini")
```
이 줄을 삭제.

- [ ] **Step 3: routes.py 수정 — google_api_key + 모델명 전달**

`backend/app/api/routes.py`에서:

기존 `get_pipeline` (line 26-39):
```python
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
변경:
```python
def get_pipeline(settings: Settings | None = None) -> ClassificationPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        if settings is None:
            settings = get_settings()
        _pipeline_instance = ClassificationPipeline(
            keyword_extractor=KeywordExtractor(settings.google_api_key, settings.gemini_model),
            vector_search=VectorSearchService(settings.google_api_key, settings.chroma_db_path, settings.gemini_embedding_model),
            reranker=Reranker(settings.google_api_key, settings.gemini_model),
            vector_search_limit=settings.vector_search_limit,
            similarity_threshold=settings.similarity_threshold,
            pipeline_timeout=settings.pipeline_timeout,
        )
    return _pipeline_instance
```

기존 classify 핸들러 (line 51):
```python
    result = await pipeline.classify(request.description, request.top_n, request.model)
```
변경:
```python
    result = await pipeline.classify(request.description, request.top_n)
```

기존 refresh_data 핸들러 (line 130):
```python
    embedder = HskEmbedder(settings.openai_api_key, settings.chroma_db_path)
```
변경:
```python
    embedder = HskEmbedder(settings.google_api_key, settings.chroma_db_path, settings.gemini_embedding_model)
```

- [ ] **Step 4: batch_routes.py 수정 — model Form 파라미터 제거**

`backend/app/api/batch_routes.py`에서:

기존 (line 49-50):
```python
    confidence_threshold: float | None = Form(default=None),
    model: str = Form(default="chatgpt-5.4-mini"),
```
변경:
```python
    confidence_threshold: float | None = Form(default=None),
```

기존 (line 62-64):
```python
        job_id = _batch_service.create_job(
            tmp.name, file.filename, effective_top_n, confidence_threshold, model,
        )
```
변경:
```python
        job_id = _batch_service.create_job(
            tmp.name, file.filename, effective_top_n, confidence_threshold,
        )
```

- [ ] **Step 5: main.py 수정 — google_api_key 참조**

`backend/app/main.py` line 81:

기존:
```python
            embedder = HskEmbedder(settings.openai_api_key, settings.chroma_db_path)
```
변경:
```python
            embedder = HskEmbedder(settings.google_api_key, settings.chroma_db_path, settings.gemini_embedding_model)
```

- [ ] **Step 6: 전체 테스트 실행**

Run: `cd backend && GOOGLE_API_KEY=test-key ADMIN_API_KEY=test-admin python -m pytest -v`
Expected: ALL PASS

- [ ] **Step 7: 커밋**

```bash
git add backend/app/models/schemas.py backend/app/api/routes.py backend/app/api/batch_routes.py backend/app/main.py backend/tests/test_batch_routes.py backend/tests/test_routes.py
git commit -m "refactor: update API routes and schemas for Gemini migration"
```

---

### Task 8: 프론트엔드 model 선택 UI 제거

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/ClassifyPage.tsx`
- Modify: `frontend/src/pages/ClassifyPage.css`
- Modify: `frontend/src/components/BatchTab.tsx`

- [ ] **Step 1: types.ts — model 필드 제거**

`frontend/src/api/types.ts`에서:

기존 ClassifyRequest (line 1-5):
```typescript
export interface ClassifyRequest {
  description: string;
  top_n: number;
  model?: string;
}
```
변경:
```typescript
export interface ClassifyRequest {
  description: string;
  top_n: number;
}
```

기존 BatchJob (line 44-56) — `model: string;` (line 53) 삭제:
```typescript
export interface BatchJob {
  job_id: string;
  file_name: string;
  status: string;
  total_items: number;
  completed_items: number;
  failed_items: number;
  top_n: number;
  confidence_threshold: number | null;
  created_at: string;
  completed_at: string | null;
}
```

- [ ] **Step 2: client.ts — uploadBatch에서 model 제거**

`frontend/src/api/client.ts`에서:

기존 uploadBatch (line 26-41):
```typescript
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
```
변경:
```typescript
export async function uploadBatch(
  file: File,
  topN: number,
  confidenceThreshold: number | null,
): Promise<BatchUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('top_n', String(topN));
  if (confidenceThreshold !== null) {
    formData.append('confidence_threshold', String(confidenceThreshold / 100));
  }
  const { data } = await api.post<BatchUploadResponse>('/batch/upload', formData);
  return data;
}
```

- [ ] **Step 3: ClassifyPage.tsx — model 관련 코드 제거**

`frontend/src/pages/ClassifyPage.tsx`에서:

1. `MODEL_OPTIONS` 상수 삭제 (line 9-13)
2. `const [model, setModel] = useState('chatgpt-5.4-mini');` 삭제 (line 20)
3. `classify()` 호출 변경 (line 53):
   기존: `const result = await classify({ description, top_n: topN, model });`
   변경: `const result = await classify({ description, top_n: topN });`
4. 모델 선택 UI 블록 삭제 (line 162-173):
```tsx
                <div className="model-control">
                  <label className="topn-label">모델</label>
                  <select
                    className="model-selector"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                  >
                    {MODEL_OPTIONS.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
```

- [ ] **Step 4: ClassifyPage.css — model CSS 제거**

`frontend/src/pages/ClassifyPage.css`에서 line 325의 빈 줄부터 line 354까지 (`.model-control` 및 `.model-selector` 관련 전체 블록) 삭제:

삭제 범위: `/* ===== Model Control ===== */` 주석부터 `.model-selector:focus { border-color: var(--color-ink); }` 닫는 괄호까지 (약 30줄)

- [ ] **Step 5: BatchTab.tsx — model 관련 코드 제거**

`frontend/src/components/BatchTab.tsx`에서:

1. `MODEL_OPTIONS` 상수 삭제 (line 9-13)
2. `const [model, setModel] = useState('chatgpt-5.4-mini');` 삭제 (line 26)
3. `uploadBatch()` 호출 변경 (line 93):
   기존: `const result = await uploadBatch(file, topN, threshold, model);`
   변경: `const result = await uploadBatch(file, topN, threshold);`
4. 모델 선택 UI 블록 삭제 (line 159-164):
```tsx
          <div className="batch-field">
            <span className="batch-field-label">모델</span>
            <select className="model-selector" value={model} onChange={(e) => setModel(e.target.value)}>
              {MODEL_OPTIONS.map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
            </select>
          </div>
```

- [ ] **Step 6: 프론트엔드 빌드 확인**

Run: `cd frontend && npm run build`
Expected: 빌드 성공, 에러 없음

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/pages/ClassifyPage.tsx frontend/src/pages/ClassifyPage.css frontend/src/components/BatchTab.tsx
git commit -m "feat: remove model selection UI, model now managed via server env vars"
```

---

### Task 9: 최종 검증

- [ ] **Step 1: 백엔드 전체 테스트**

Run: `cd backend && GOOGLE_API_KEY=test-key ADMIN_API_KEY=test-admin python -m pytest -v`
Expected: ALL PASS

- [ ] **Step 2: 프론트엔드 빌드**

Run: `cd frontend && npm run build`
Expected: 빌드 성공

- [ ] **Step 3: openai 잔여 참조 확인**

Run: `grep -r "openai\|OPENAI\|openai_api_key" backend/ --include="*.py" -l`
Expected: 매칭 없음

Run: `grep -r "chatgpt\|MODEL_OPTIONS\|model-selector\|model-control" frontend/src/ -l`
Expected: 매칭 없음

- [ ] **Step 4: 커밋 (잔여 수정 있을 경우)**

있다면 수정 후 커밋.
