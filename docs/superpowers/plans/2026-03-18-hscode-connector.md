# HSCode Connector 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** R&D 기술 설명(자연어)을 입력하면 RAG 파이프라인을 통해 관련 HSK 10자리 코드를 Top N으로 제시하는 웹 애플리케이션 구축

**Architecture:** FastAPI 백엔드가 3단계 파이프라인(LLM 키워드 추출 → ChromaDB 벡터 검색 → LLM 리랭킹)을 오케스트레이션하고, React 프론트엔드가 입력/결과 UI를 제공한다. HSK 데이터는 관세청에서 수집하여 SQLite(원본)와 ChromaDB(벡터)에 이중 저장한다.

**Tech Stack:** FastAPI, React, ChromaDB, SQLite, OpenAI GPT-4o, OpenAI text-embedding-3-small

**Spec:** `docs/superpowers/specs/2026-03-18-hscode-connector-design.md`

**포트 할당 (PORT_REGISTRY 규칙 기준):**
- Backend: 호스트 `8011`, 컨테이너 `8000`
- Frontend (Nginx prod): 호스트 `8092`, 컨테이너 `80`
- Frontend (Vite dev): 호스트 `5180`, 컨테이너 `5173`

---

## 파일 구조

```
11_hscode-connector/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    — FastAPI 앱, CORS, 라우터 등록
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes.py              — API 엔드포인트 (classify, hsk, refresh)
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py              — Settings (환경변수 로드)
│   │   │   └── pipeline.py            — 3단계 파이프라인 오케스트레이션
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── keyword_extractor.py   — Step 1: LLM 키워드 추출
│   │   │   ├── vector_search.py       — Step 2: ChromaDB 벡터 검색
│   │   │   └── reranker.py            — Step 3: LLM 리랭킹
│   │   ├── data/
│   │   │   ├── __init__.py
│   │   │   ├── crawler.py             — 관세청 HSK 데이터 수집
│   │   │   └── embedder.py            — HSK 임베딩 생성/ChromaDB 저장
│   │   └── models/
│   │       ├── __init__.py
│   │       └── schemas.py             — Pydantic 요청/응답 모델
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_schemas.py
│   │   ├── test_config.py
│   │   ├── test_keyword_extractor.py
│   │   ├── test_vector_search.py
│   │   ├── test_reranker.py
│   │   ├── test_pipeline.py
│   │   └── test_routes.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── api/
│   │   │   └── client.ts              — API 호출 함수
│   │   ├── pages/
│   │   │   ├── ClassifyPage.tsx        — 메인 분류 화면
│   │   │   └── BrowsePage.tsx          — HSK 코드 탐색 화면
│   │   └── components/
│   │       ├── ResultTable.tsx          — 결과 테이블
│   │       └── HskTree.tsx             — 계층 트리
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── data/                               — SQLite DB, ChromaDB (gitignore)
├── docker-compose.yml
├── .gitignore
└── CLAUDE.md
```

---

## Task 1: 프로젝트 초기화 및 설정

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/.env.example`
- Create: `backend/app/__init__.py`
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/core/config.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_config.py`
- Create: `.gitignore`
- Create: `CLAUDE.md`

- [ ] **Step 1: .gitignore 작성**

```
# .gitignore
__pycache__/
*.pyc
.env
data/
*.db
node_modules/
dist/
.vite/
```

- [ ] **Step 2: CLAUDE.md 작성**

```markdown
# 11_hscode-connector

R&D 기술 설명 → HSK 10자리 코드 매핑 시스템 (RAG 파이프라인)

## 스택
- Backend: FastAPI + OpenAI GPT-4o + ChromaDB + SQLite
- Frontend: React + Vite + TypeScript

## 포트
- Backend: 8011 (호스트) → 8000 (컨테이너)
- Frontend: 8092 (Nginx prod) / 5180 (Vite dev)

## 실행
- Backend: `cd backend && uvicorn app.main:app --reload --port 8000`
- Frontend: `cd frontend && npm run dev`
- 테스트: `cd backend && pytest -v`
```

- [ ] **Step 3: requirements.txt 작성**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
openai==1.58.1
chromadb==0.5.23
pydantic==2.10.4
pydantic-settings==2.7.1
httpx==0.28.1
beautifulsoup4==4.12.3
lxml==5.3.0
sse-starlette==2.2.1
pytest==8.3.4
pytest-asyncio==0.25.0
```

- [ ] **Step 4: .env.example 작성**

```
OPENAI_API_KEY=sk-your-key-here
ADMIN_API_KEY=your-admin-key-here
CHROMA_DB_PATH=./data/chromadb
SQLITE_DB_PATH=./data/hsk.db
BACKEND_PORT=8011
```

- [ ] **Step 5: config.py 테스트 작성**

```python
# backend/tests/test_config.py
import os
import pytest


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-test")
    from app.core.config import Settings
    settings = Settings()
    assert settings.openai_api_key == "test-key"
    assert settings.admin_api_key == "admin-test"


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-test")
    from app.core.config import Settings
    settings = Settings()
    assert settings.chroma_db_path == "./data/chromadb"
    assert settings.sqlite_db_path == "./data/hsk.db"
    assert settings.max_input_length == 2000
    assert settings.max_top_n == 20
    assert settings.vector_search_limit == 50
    assert settings.similarity_threshold == 0.3
```

- [ ] **Step 6: 테스트 실행하여 실패 확인**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.config'`

- [ ] **Step 7: config.py 구현**

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str
    admin_api_key: str
    chroma_db_path: str = "./data/chromadb"
    sqlite_db_path: str = "./data/hsk.db"
    max_input_length: int = 2000
    max_top_n: int = 20
    vector_search_limit: int = 50
    similarity_threshold: float = 0.3
    pipeline_timeout: int = 30

    model_config = {"env_file": ".env"}
```

- [ ] **Step 8: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 9: __init__.py 파일 생성**

빈 `__init__.py` 파일 생성:
- `backend/app/__init__.py`
- `backend/app/core/__init__.py`
- `backend/app/api/__init__.py`
- `backend/app/services/__init__.py`
- `backend/app/data/__init__.py`
- `backend/app/models/__init__.py`
- `backend/tests/__init__.py`

- [ ] **Step 10: 커밋**

```bash
git add -A
git commit -m "chore: initialize project structure with config and dependencies"
```

---

## Task 2: Pydantic 스키마 정의

**Files:**
- Create: `backend/app/models/schemas.py`
- Create: `backend/tests/test_schemas.py`

- [ ] **Step 1: 스키마 테스트 작성**

```python
# backend/tests/test_schemas.py
import pytest
from app.models.schemas import ClassifyRequest, ClassifyResult, ClassifyResponse


def test_classify_request_defaults():
    req = ClassifyRequest(description="리튬이온 배터리 양극재 제조 기술")
    assert req.top_n == 5
    assert req.description == "리튬이온 배터리 양극재 제조 기술"


def test_classify_request_validates_top_n():
    with pytest.raises(ValueError):
        ClassifyRequest(description="test", top_n=25)  # max is 20


def test_classify_request_validates_short_input():
    with pytest.raises(ValueError):
        ClassifyRequest(description="짧은")  # < 10 chars


def test_classify_request_validates_long_input():
    with pytest.raises(ValueError):
        ClassifyRequest(description="가" * 2001)  # > 2000 chars


def test_classify_result_fields():
    result = ClassifyResult(
        rank=1,
        hsk_code="8507601000",
        name_kr="리튬이온 축전지",
        name_en="Lithium-ion accumulators",
        confidence=0.92,
        reason="양극재는 리튬이온 축전지의 핵심 구성 요소",
    )
    assert result.hsk_code == "8507601000"
    assert result.confidence == 0.92


def test_classify_response_fields():
    resp = ClassifyResponse(
        results=[],
        keywords_extracted=["양극재"],
        processing_time_ms=5200,
    )
    assert resp.processing_time_ms == 5200
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `cd backend && python -m pytest tests/test_schemas.py -v`
Expected: FAIL

- [ ] **Step 3: schemas.py 구현**

```python
# backend/app/models/schemas.py
from pydantic import BaseModel, Field, field_validator


class ClassifyRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=2000)
    top_n: int = Field(default=5, ge=1, le=20)

    @field_validator("description")
    @classmethod
    def description_not_too_short(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError("기술 설명은 최소 10자 이상이어야 합니다")
        return v.strip()


class ClassifyResult(BaseModel):
    rank: int
    hsk_code: str
    name_kr: str
    name_en: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class ClassifyResponse(BaseModel):
    results: list[ClassifyResult]
    keywords_extracted: list[str]
    processing_time_ms: int


class HskCodeDetail(BaseModel):
    code: str
    name_kr: str
    name_en: str | None = None
    level: int
    parent_code: str | None = None
    description: str | None = None
    children: list["HskCodeDetail"] = []


class HskSearchResult(BaseModel):
    results: list[HskCodeDetail]
    total: int


class ErrorResponse(BaseModel):
    detail: str
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_schemas.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/models/schemas.py backend/tests/test_schemas.py
git commit -m "feat: add Pydantic request/response schemas"
```

---

## Task 3: 관세청 데이터 수집기 (crawler)

**Files:**
- Create: `backend/app/data/crawler.py`
- Create: `backend/tests/test_crawler.py`

- [ ] **Step 1: crawler 테스트 작성**

관세청 API 실제 호출은 통합 테스트에서 수행. 여기서는 파싱 로직 단위 테스트.

```python
# backend/tests/test_crawler.py
import pytest
from app.data.crawler import HskCrawler, HskRecord


def test_hsk_record_creation():
    record = HskRecord(
        code="8507601000",
        name_kr="리튬이온 축전지",
        name_en="Lithium-ion accumulators",
        level=5,
        parent_code="850760",
        description="",
    )
    assert record.code == "8507601000"
    assert record.level == 5


def test_format_hsk_code():
    assert HskCrawler.format_code("8507601000") == "8507.60-1000"
    assert HskCrawler.format_code("85") == "85"
    assert HskCrawler.format_code("8507") == "85.07"
    assert HskCrawler.format_code("850760") == "8507.60"


def test_determine_level():
    assert HskCrawler.determine_level("85") == 1          # 류 (2자리)
    assert HskCrawler.determine_level("8507") == 2        # 호 (4자리)
    assert HskCrawler.determine_level("850760") == 3      # 소호 (6자리)
    assert HskCrawler.determine_level("85076010") == 4    # 통계부호 (8자리)
    assert HskCrawler.determine_level("8507601000") == 5  # HSK (10자리)


def test_determine_parent():
    assert HskCrawler.determine_parent("8507601000") == "85076010"
    assert HskCrawler.determine_parent("85076010") == "850760"
    assert HskCrawler.determine_parent("850760") == "8507"
    assert HskCrawler.determine_parent("8507") == "85"
    assert HskCrawler.determine_parent("85") is None
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `cd backend && python -m pytest tests/test_crawler.py -v`
Expected: FAIL

- [ ] **Step 3: crawler.py 구현**

```python
# backend/app/data/crawler.py
from dataclasses import dataclass
import httpx
from bs4 import BeautifulSoup
import sqlite3
import logging

logger = logging.getLogger(__name__)


@dataclass
class HskRecord:
    code: str
    name_kr: str
    name_en: str
    level: int
    parent_code: str | None
    description: str


class HskCrawler:
    """관세청 품목분류표에서 HSK 코드를 수집하여 SQLite에 저장"""

    BASE_URL = "https://unipass.customs.go.kr"

    @staticmethod
    def format_code(code: str) -> str:
        """10자리 숫자 코드를 표시 형식으로 변환"""
        code = code.strip()
        if len(code) <= 2:
            return code
        if len(code) == 4:
            return f"{code[:2]}.{code[2:]}"
        if len(code) == 6:
            return f"{code[:4]}.{code[4:]}"
        if len(code) == 8:
            return f"{code[:4]}.{code[4:6]}-{code[6:]}"
        if len(code) == 10:
            return f"{code[:4]}.{code[4:6]}-{code[6:]}"
        return code

    @staticmethod
    def determine_level(code: str) -> int:
        """코드 길이로 계층 수준 결정"""
        length_to_level = {2: 1, 4: 2, 6: 3, 8: 4, 10: 5}
        return length_to_level.get(len(code), 0)

    @staticmethod
    def determine_parent(code: str) -> str | None:
        """부모 코드 결정"""
        parent_lengths = {10: 8, 8: 6, 6: 4, 4: 2}
        parent_len = parent_lengths.get(len(code))
        if parent_len is None:
            return None
        return code[:parent_len]

    async def fetch_all(self) -> list[HskRecord]:
        """관세청에서 전체 HSK 코드 수집. 구현은 관세청 API 구조에 따라 조정 필요."""
        records: list[HskRecord] = []
        async with httpx.AsyncClient(timeout=60) as client:
            # 관세청 Open API 또는 웹 페이지에서 데이터 수집
            # 실제 엔드포인트는 관세청 사이트 구조에 맞게 조정
            logger.info("관세청 HSK 데이터 수집 시작")
            # TODO: 실제 관세청 API 엔드포인트 연동
            # 각 류(01~97)별로 하위 코드를 순회하며 수집
            for chapter in range(1, 98):
                chapter_code = f"{chapter:02d}"
                try:
                    chapter_records = await self._fetch_chapter(client, chapter_code)
                    records.extend(chapter_records)
                    logger.info(f"류 {chapter_code}: {len(chapter_records)}건 수집")
                except Exception as e:
                    logger.error(f"류 {chapter_code} 수집 실패: {e}")
        logger.info(f"총 {len(records)}건 수집 완료")
        return records

    async def _fetch_chapter(self, client: httpx.AsyncClient, chapter: str) -> list[HskRecord]:
        """특정 류의 하위 HSK 코드 수집. 관세청 API 구조에 따라 구현."""
        # TODO: 실제 관세청 API/페이지 구조에 맞게 구현
        return []

    def save_to_sqlite(self, records: list[HskRecord], db_path: str) -> None:
        """수집한 레코드를 SQLite에 저장"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hsk_codes (
                code TEXT PRIMARY KEY,
                name_kr TEXT NOT NULL,
                name_en TEXT,
                level INTEGER NOT NULL,
                parent_code TEXT,
                description TEXT
            )
        """)
        cursor.execute("DELETE FROM hsk_codes")
        cursor.executemany(
            "INSERT INTO hsk_codes (code, name_kr, name_en, level, parent_code, description) VALUES (?, ?, ?, ?, ?, ?)",
            [(r.code, r.name_kr, r.name_en, r.level, r.parent_code, r.description) for r in records],
        )
        conn.commit()
        conn.close()
        logger.info(f"SQLite 저장 완료: {len(records)}건 → {db_path}")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_crawler.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/data/crawler.py backend/tests/test_crawler.py
git commit -m "feat: add HSK data crawler with code formatting and level detection"
```

---

## Task 4: 임베딩 생성기 (embedder)

**Files:**
- Create: `backend/app/data/embedder.py`
- Create: `backend/tests/test_embedder.py`

- [ ] **Step 1: embedder 테스트 작성**

```python
# backend/tests/test_embedder.py
import pytest
from unittest.mock import MagicMock, patch
from app.data.embedder import HskEmbedder


def test_build_embedding_text():
    text = HskEmbedder.build_embedding_text("리튬이온 축전지", "Lithium-ion accumulators")
    assert "리튬이온 축전지" in text
    assert "Lithium-ion accumulators" in text


def test_build_embedding_text_no_english():
    text = HskEmbedder.build_embedding_text("리튬이온 축전지", None)
    assert "리튬이온 축전지" in text


def test_chunk_list():
    items = list(range(10))
    chunks = list(HskEmbedder.chunk_list(items, 3))
    assert len(chunks) == 4
    assert chunks[0] == [0, 1, 2]
    assert chunks[-1] == [9]
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `cd backend && python -m pytest tests/test_embedder.py -v`
Expected: FAIL

- [ ] **Step 3: embedder.py 구현**

```python
# backend/app/data/embedder.py
import sqlite3
import logging
from typing import Iterator
from openai import OpenAI
import chromadb

logger = logging.getLogger(__name__)


class HskEmbedder:
    """SQLite의 HSK 코드를 임베딩하여 ChromaDB에 저장"""

    EMBEDDING_MODEL = "text-embedding-3-small"
    BATCH_SIZE = 100

    def __init__(self, openai_api_key: str, chroma_db_path: str):
        self.openai_client = OpenAI(api_key=openai_api_key)
        self.chroma_client = chromadb.PersistentClient(path=chroma_db_path)

    @staticmethod
    def build_embedding_text(name_kr: str, name_en: str | None) -> str:
        """임베딩용 텍스트 생성"""
        if name_en:
            return f"{name_kr} ({name_en})"
        return name_kr

    @staticmethod
    def chunk_list(items: list, size: int) -> Iterator[list]:
        """리스트를 지정 크기로 분할"""
        for i in range(0, len(items), size):
            yield items[i : i + size]

    def embed_from_sqlite(self, sqlite_db_path: str) -> None:
        """SQLite에서 HSK 코드를 읽어 ChromaDB에 임베딩 저장"""
        conn = sqlite3.connect(sqlite_db_path)
        cursor = conn.cursor()
        rows = cursor.execute(
            "SELECT code, name_kr, name_en, level, parent_code FROM hsk_codes"
        ).fetchall()
        conn.close()

        collection = self.chroma_client.get_or_create_collection(
            name="hsk_codes",
            metadata={"hnsw:space": "cosine"},
        )
        # 기존 데이터 삭제 후 재생성
        self.chroma_client.delete_collection("hsk_codes")
        collection = self.chroma_client.create_collection(
            name="hsk_codes",
            metadata={"hnsw:space": "cosine"},
        )

        for batch in self.chunk_list(rows, self.BATCH_SIZE):
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
        """OpenAI 임베딩 API 호출"""
        response = self.openai_client.embeddings.create(
            model=self.EMBEDDING_MODEL,
            input=texts,
        )
        return [item.embedding for item in response.data]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_embedder.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/data/embedder.py backend/tests/test_embedder.py
git commit -m "feat: add HSK embedder for ChromaDB vector storage"
```

---

## Task 5: Step 1 — 키워드 추출 서비스

**Files:**
- Create: `backend/app/services/keyword_extractor.py`
- Create: `backend/tests/test_keyword_extractor.py`

- [ ] **Step 1: 키워드 추출 테스트 작성**

```python
# backend/tests/test_keyword_extractor.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.services.keyword_extractor import KeywordExtractor


def test_build_prompt():
    prompt = KeywordExtractor.build_prompt("리튬이온 배터리 양극재 제조 기술")
    assert "리튬이온 배터리 양극재 제조 기술" in prompt
    assert "제품" in prompt or "물질" in prompt


def test_parse_keywords():
    raw = '["양극재", "cathode material", "리튬이온 배터리", "NCM"]'
    keywords = KeywordExtractor.parse_keywords(raw)
    assert "양극재" in keywords
    assert "cathode material" in keywords
    assert len(keywords) == 4


def test_parse_keywords_handles_malformed():
    raw = "양극재, cathode material, 리튬이온 배터리"
    keywords = KeywordExtractor.parse_keywords(raw)
    assert len(keywords) >= 2
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `cd backend && python -m pytest tests/test_keyword_extractor.py -v`
Expected: FAIL

- [ ] **Step 3: keyword_extractor.py 구현**

```python
# backend/app/services/keyword_extractor.py
import json
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 R&D 기술 설명에서 관련 무역 상품을 추출하는 전문가입니다.
사용자가 제공하는 기술 설명을 분석하여, 해당 기술과 관련된 제품, 물질, 부품, 장비를 한국어와 영어로 추출하세요.
직접 언급되지 않았더라도 해당 기술로 생산되거나 사용되는 파생 제품도 포함하세요.
결과는 JSON 배열 형식으로만 반환하세요. 예: ["양극재", "cathode material", "리튬이온 배터리"]"""


class KeywordExtractor:
    """Step 1: R&D 기술 설명에서 관련 제품/물질 키워드를 추출"""

    def __init__(self, openai_api_key: str):
        self.client = AsyncOpenAI(api_key=openai_api_key)

    @staticmethod
    def build_prompt(description: str) -> str:
        return f"다음 R&D 기술 설명에서 관련 제품, 물질, 부품, 장비를 한국어와 영어로 추출하세요:\n\n{description}"

    @staticmethod
    def parse_keywords(raw: str) -> list[str]:
        """LLM 응답에서 키워드 리스트 파싱"""
        raw = raw.strip()
        try:
            keywords = json.loads(raw)
            if isinstance(keywords, list):
                return [k.strip() for k in keywords if isinstance(k, str) and k.strip()]
        except json.JSONDecodeError:
            pass
        # JSON 파싱 실패 시 콤마/줄바꿈으로 분리
        keywords = [k.strip().strip('"').strip("'") for k in raw.replace("\n", ",").split(",")]
        return [k for k in keywords if k]

    async def extract(self, description: str, max_retries: int = 2) -> list[str]:
        """기술 설명에서 키워드 추출 (실패 시 최대 max_retries회 재시도)"""
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": self.build_prompt(description)},
                    ],
                    temperature=0.2,
                )
                raw = response.choices[0].message.content or ""
                keywords = self.parse_keywords(raw)
                logger.info(f"키워드 추출 완료: {len(keywords)}개 — {keywords}")
                return keywords
            except Exception as e:
                last_error = e
                logger.warning(f"키워드 추출 재시도 {attempt + 1}/{max_retries + 1}: {e}")
        raise last_error
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_keyword_extractor.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services/keyword_extractor.py backend/tests/test_keyword_extractor.py
git commit -m "feat: add keyword extractor service (pipeline step 1)"
```

---

## Task 6: Step 2 — 벡터 검색 서비스

**Files:**
- Create: `backend/app/services/vector_search.py`
- Create: `backend/tests/test_vector_search.py`

- [ ] **Step 1: 벡터 검색 테스트 작성**

```python
# backend/tests/test_vector_search.py
import pytest
from app.services.vector_search import VectorSearchService, SearchCandidate


def test_search_candidate_creation():
    c = SearchCandidate(code="8507601000", name="리튬이온 축전지", distance=0.15)
    assert c.code == "8507601000"
    assert c.distance == 0.15


def test_deduplicate_candidates():
    candidates = [
        SearchCandidate(code="8507601000", name="리튬이온 축전지", distance=0.1),
        SearchCandidate(code="8507601000", name="리튬이온 축전지", distance=0.2),
        SearchCandidate(code="2827399000", name="니켈 코발트 산화물", distance=0.3),
    ]
    deduped = VectorSearchService.deduplicate(candidates)
    assert len(deduped) == 2
    # 동일 코드는 가장 낮은 distance(가장 유사한) 유지
    assert deduped[0].distance == 0.1


def test_filter_by_threshold():
    candidates = [
        SearchCandidate(code="A", name="a", distance=0.1),
        SearchCandidate(code="B", name="b", distance=0.5),
        SearchCandidate(code="C", name="c", distance=0.8),
    ]
    filtered = VectorSearchService.filter_by_threshold(candidates, threshold=0.3)
    assert len(filtered) == 1
    assert filtered[0].code == "A"
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `cd backend && python -m pytest tests/test_vector_search.py -v`
Expected: FAIL

- [ ] **Step 3: vector_search.py 구현**

```python
# backend/app/services/vector_search.py
from dataclasses import dataclass
import logging
from openai import OpenAI
import chromadb

logger = logging.getLogger(__name__)


@dataclass
class SearchCandidate:
    code: str
    name: str
    distance: float


class VectorSearchService:
    """Step 2: 키워드를 임베딩하여 ChromaDB에서 유사 HSK 코드 검색"""

    EMBEDDING_MODEL = "text-embedding-3-small"

    def __init__(self, openai_api_key: str, chroma_db_path: str):
        self.openai_client = OpenAI(api_key=openai_api_key)
        self.chroma_client = chromadb.PersistentClient(path=chroma_db_path)

    @staticmethod
    def deduplicate(candidates: list[SearchCandidate]) -> list[SearchCandidate]:
        """동일 코드 중복 제거, 가장 낮은 distance 유지"""
        best: dict[str, SearchCandidate] = {}
        for c in candidates:
            if c.code not in best or c.distance < best[c.code].distance:
                best[c.code] = c
        return sorted(best.values(), key=lambda x: x.distance)

    @staticmethod
    def filter_by_threshold(candidates: list[SearchCandidate], threshold: float) -> list[SearchCandidate]:
        """distance가 threshold 이하인 후보만 남김 (cosine distance: 낮을수록 유사)"""
        return [c for c in candidates if c.distance <= threshold]

    def search(self, keywords: list[str], limit: int = 50, threshold: float = 0.3) -> list[SearchCandidate]:
        """키워드별로 벡터 검색 후 합산/중복제거"""
        collection = self.chroma_client.get_collection("hsk_codes")
        all_candidates: list[SearchCandidate] = []

        for keyword in keywords:
            embedding = self._get_embedding(keyword)
            results = collection.query(
                query_embeddings=[embedding],
                n_results=min(limit, 50),
                include=["documents", "distances", "metadatas"],
            )
            if results["ids"] and results["ids"][0]:
                for code, doc, dist in zip(
                    results["ids"][0],
                    results["documents"][0],
                    results["distances"][0],
                ):
                    all_candidates.append(SearchCandidate(code=code, name=doc, distance=dist))

        deduped = self.deduplicate(all_candidates)
        filtered = self.filter_by_threshold(deduped, threshold)
        result = filtered[:limit]
        logger.info(f"벡터 검색 완료: {len(keywords)}개 키워드 → {len(result)}개 후보")
        return result

    def _get_embedding(self, text: str) -> list[float]:
        response = self.openai_client.embeddings.create(
            model=self.EMBEDDING_MODEL,
            input=[text],
        )
        return response.data[0].embedding
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_vector_search.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services/vector_search.py backend/tests/test_vector_search.py
git commit -m "feat: add vector search service (pipeline step 2)"
```

---

## Task 7: Step 3 — 리랭킹 서비스

**Files:**
- Create: `backend/app/services/reranker.py`
- Create: `backend/tests/test_reranker.py`

- [ ] **Step 1: 리랭킹 테스트 작성**

```python
# backend/tests/test_reranker.py
import pytest
import json
from app.services.reranker import Reranker


def test_build_candidates_text():
    from app.services.vector_search import SearchCandidate
    candidates = [
        SearchCandidate(code="8507601000", name="리튬이온 축전지", distance=0.1),
        SearchCandidate(code="2827399000", name="니켈 코발트 산화물", distance=0.2),
    ]
    text = Reranker.build_candidates_text(candidates)
    assert "8507601000" in text
    assert "리튬이온 축전지" in text
    assert "2827399000" in text


def test_parse_rerank_response_valid():
    raw = json.dumps([
        {"code": "8507601000", "confidence": 0.92, "reason": "직접 관련"},
        {"code": "2827399000", "confidence": 0.85, "reason": "원료 관련"},
    ])
    results = Reranker.parse_response(raw)
    assert len(results) == 2
    assert results[0]["code"] == "8507601000"
    assert results[0]["confidence"] == 0.92


def test_parse_rerank_response_extracts_json_from_markdown():
    raw = '```json\n[{"code": "8507601000", "confidence": 0.9, "reason": "관련"}]\n```'
    results = Reranker.parse_response(raw)
    assert len(results) == 1
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `cd backend && python -m pytest tests/test_reranker.py -v`
Expected: FAIL

- [ ] **Step 3: reranker.py 구현**

```python
# backend/app/services/reranker.py
import json
import re
import logging
from openai import AsyncOpenAI
from app.services.vector_search import SearchCandidate

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 HS 코드 분류 전문가입니다.
사용자가 제공하는 R&D 기술 설명과 후보 HSK 코드 목록을 비교하여,
관련도가 높은 순서대로 코드를 선정하고 신뢰도 점수와 선정 사유를 제시하세요.

반드시 후보 목록에 있는 코드만 선택하세요. 새로운 코드를 만들지 마세요.

결과는 JSON 배열로만 반환하세요:
[{"code": "코드", "confidence": 0.0~1.0, "reason": "선정 사유"}, ...]"""


class Reranker:
    """Step 3: LLM을 사용하여 후보 HSK 코드를 리랭킹"""

    def __init__(self, openai_api_key: str):
        self.client = AsyncOpenAI(api_key=openai_api_key)

    @staticmethod
    def build_candidates_text(candidates: list[SearchCandidate]) -> str:
        lines = [f"- {c.code}: {c.name}" for c in candidates]
        return "\n".join(lines)

    @staticmethod
    def parse_response(raw: str) -> list[dict]:
        """LLM 응답에서 JSON 배열 파싱"""
        raw = raw.strip()
        # markdown 코드블록 제거
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

    async def rerank(
        self, description: str, candidates: list[SearchCandidate], top_n: int, max_retries: int = 2
    ) -> list[dict]:
        """후보 코드를 리랭킹하여 Top N 반환 (실패 시 최대 max_retries회 재시도)"""
        candidates_text = self.build_candidates_text(candidates)
        user_prompt = (
            f"## R&D 기술 설명\n{description}\n\n"
            f"## 후보 HSK 코드 목록\n{candidates_text}\n\n"
            f"위 기술 설명과 가장 관련 있는 HSK 코드를 최대 {top_n}개 선정하세요."
        )

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.1,
                )
                raw = response.choices[0].message.content or ""
                results = self.parse_response(raw)
                logger.info(f"리랭킹 완료: {len(results)}개 선정")
                return results[:top_n]
            except Exception as e:
                last_error = e
                logger.warning(f"리랭킹 재시도 {attempt + 1}/{max_retries + 1}: {e}")
        raise last_error
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_reranker.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services/reranker.py backend/tests/test_reranker.py
git commit -m "feat: add reranker service (pipeline step 3)"
```

---

## Task 8: 파이프라인 오케스트레이션

**Files:**
- Create: `backend/app/core/pipeline.py`
- Create: `backend/tests/test_pipeline.py`

- [ ] **Step 1: 파이프라인 테스트 작성**

```python
# backend/tests/test_pipeline.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.pipeline import ClassificationPipeline, PipelineStep


def test_pipeline_step_enum():
    assert PipelineStep.KEYWORD_EXTRACTION.value == "keyword_extraction"
    assert PipelineStep.VECTOR_SEARCH.value == "vector_search"
    assert PipelineStep.RERANKING.value == "reranking"


@pytest.mark.asyncio
async def test_pipeline_runs_all_steps():
    mock_extractor = AsyncMock()
    mock_extractor.extract.return_value = ["양극재", "cathode material"]

    mock_search = MagicMock()
    from app.services.vector_search import SearchCandidate
    mock_search.search.return_value = [
        SearchCandidate(code="8507601000", name="리튬이온 축전지", distance=0.1),
    ]

    mock_reranker = AsyncMock()
    mock_reranker.rerank.return_value = [
        {"code": "8507601000", "confidence": 0.92, "reason": "관련"},
    ]

    pipeline = ClassificationPipeline(
        keyword_extractor=mock_extractor,
        vector_search=mock_search,
        reranker=mock_reranker,
    )
    result = await pipeline.classify("리튬이온 배터리 양극재 제조 기술", top_n=5)

    assert result.keywords == ["양극재", "cathode material"]
    assert len(result.results) == 1
    assert result.results[0]["code"] == "8507601000"
    mock_extractor.extract.assert_called_once()
    mock_search.search.assert_called_once()
    mock_reranker.rerank.assert_called_once()
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `cd backend && python -m pytest tests/test_pipeline.py -v`
Expected: FAIL

- [ ] **Step 3: pipeline.py 구현**

```python
# backend/app/core/pipeline.py
import asyncio
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncGenerator, Callable
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
    """3단계 분류 파이프라인 오케스트레이션"""

    def __init__(
        self,
        keyword_extractor: KeywordExtractor,
        vector_search: VectorSearchService,
        reranker: Reranker,
        vector_search_limit: int = 50,
        similarity_threshold: float = 0.3,
        pipeline_timeout: int = 30,
    ):
        self.keyword_extractor = keyword_extractor
        self.vector_search = vector_search
        self.reranker = reranker
        self.vector_search_limit = vector_search_limit
        self.similarity_threshold = similarity_threshold
        self.pipeline_timeout = pipeline_timeout

    async def classify(
        self,
        description: str,
        top_n: int = 5,
        on_step: Callable[[PipelineStep], None] | None = None,
    ) -> PipelineResult:
        """기술 설명을 분류하여 HSK 코드 반환 (타임아웃: pipeline_timeout초)"""
        return await asyncio.wait_for(
            self._classify_impl(description, top_n, on_step),
            timeout=self.pipeline_timeout,
        )

    async def _classify_impl(
        self,
        description: str,
        top_n: int = 5,
        on_step: Callable[[PipelineStep], None] | None = None,
    ) -> PipelineResult:
        start = time.time()

        # Step 1: 키워드 추출
        if on_step:
            on_step(PipelineStep.KEYWORD_EXTRACTION)
        keywords = await self.keyword_extractor.extract(description)

        # Step 2: 벡터 검색
        if on_step:
            on_step(PipelineStep.VECTOR_SEARCH)
        candidates = self.vector_search.search(
            keywords,
            limit=self.vector_search_limit,
            threshold=self.similarity_threshold,
        )

        # Step 3: 리랭킹
        if on_step:
            on_step(PipelineStep.RERANKING)
        results = await self.reranker.rerank(description, candidates, top_n)

        elapsed_ms = int((time.time() - start) * 1000)
        logger.info(f"파이프라인 완료: {elapsed_ms}ms")

        return PipelineResult(
            keywords=keywords,
            results=results,
            processing_time_ms=elapsed_ms,
        )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/core/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: add classification pipeline orchestration"
```

---

## Task 9: FastAPI 앱 및 API 라우트

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/app/api/routes.py`
- Create: `backend/tests/test_routes.py`

- [ ] **Step 1: 라우트 테스트 작성**

```python
# backend/tests/test_routes.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import create_app


@pytest.fixture
def app():
    with patch.dict("os.environ", {
        "OPENAI_API_KEY": "test-key",
        "ADMIN_API_KEY": "test-admin",
    }):
        return create_app()


@pytest.mark.asyncio
async def test_classify_validates_short_input(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/classify", json={"description": "짧은"})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_classify_validates_top_n(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/classify",
            json={"description": "리튬이온 배터리 양극재 제조 기술", "top_n": 25},
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_refresh_requires_admin_key(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 헤더 없이 호출 시 422
        resp = await client.post("/api/v1/data/refresh")
        assert resp.status_code == 422
        # 잘못된 키로 호출 시 403
        resp = await client.post("/api/v1/data/refresh", headers={"X-Admin-Key": "wrong"})
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_health_endpoint(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
```

- [ ] **Step 2: 테스트 실행하여 실패 확인**

Run: `cd backend && python -m pytest tests/test_routes.py -v`
Expected: FAIL

- [ ] **Step 3: main.py 구현**

```python
# backend/app/main.py
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router, ensure_data_dirs
from app.core.config import Settings


def create_app() -> FastAPI:
    app = FastAPI(title="HSCode Connector", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api/v1")

    @app.on_event("startup")
    async def startup():
        try:
            settings = Settings()
            ensure_data_dirs(settings)
        except Exception:
            pass  # .env 없이 테스트 실행 시 무시

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 4: routes.py 구현**

```python
# backend/app/api/routes.py
import os
import sqlite3
import logging
from fastapi import APIRouter, HTTPException, Header
from app.core.config import Settings
from app.core.pipeline import ClassificationPipeline
from app.services.keyword_extractor import KeywordExtractor
from app.services.vector_search import VectorSearchService
from app.services.reranker import Reranker
from app.data.crawler import HskCrawler
from app.data.embedder import HskEmbedder
from app.models.schemas import (
    ClassifyRequest,
    ClassifyResult,
    ClassifyResponse,
    HskCodeDetail,
    HskSearchResult,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def get_settings() -> Settings:
    return Settings()


def get_pipeline(settings: Settings) -> ClassificationPipeline:
    return ClassificationPipeline(
        keyword_extractor=KeywordExtractor(settings.openai_api_key),
        vector_search=VectorSearchService(settings.openai_api_key, settings.chroma_db_path),
        reranker=Reranker(settings.openai_api_key),
        vector_search_limit=settings.vector_search_limit,
        similarity_threshold=settings.similarity_threshold,
        pipeline_timeout=settings.pipeline_timeout,
    )


def ensure_data_dirs(settings: Settings) -> None:
    """data 디렉터리가 없으면 생성"""
    os.makedirs(os.path.dirname(settings.sqlite_db_path), exist_ok=True)
    os.makedirs(settings.chroma_db_path, exist_ok=True)


@router.post("/classify", response_model=ClassifyResponse)
async def classify(request: ClassifyRequest):
    settings = get_settings()
    pipeline = get_pipeline(settings)
    result = await pipeline.classify(request.description, request.top_n)

    # 리랭킹 결과를 ClassifyResult로 변환 (코드를 표시 형식으로 포맷팅)
    conn = sqlite3.connect(settings.sqlite_db_path)
    cursor = conn.cursor()
    classify_results = []
    for i, item in enumerate(result.results, 1):
        row = cursor.execute(
            "SELECT name_kr, name_en FROM hsk_codes WHERE code = ?", (item["code"],)
        ).fetchone()
        classify_results.append(ClassifyResult(
            rank=i,
            hsk_code=HskCrawler.format_code(item["code"]),
            name_kr=row[0] if row else item.get("code", ""),
            name_en=row[1] if row else None,
            confidence=item.get("confidence", 0.0),
            reason=item.get("reason", ""),
        ))
    conn.close()

    return ClassifyResponse(
        results=classify_results,
        keywords_extracted=result.keywords,
        processing_time_ms=result.processing_time_ms,
    )


# 주의: /hsk/search를 /hsk/{code}보다 먼저 등록해야 경로 충돌 방지
@router.get("/hsk/search", response_model=HskSearchResult)
async def search_hsk(q: str, limit: int = 20):
    settings = get_settings()
    conn = sqlite3.connect(settings.sqlite_db_path)
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT code, name_kr, name_en, level, parent_code, description FROM hsk_codes WHERE name_kr LIKE ? OR name_en LIKE ? OR code LIKE ? LIMIT ?",
        (f"%{q}%", f"%{q}%", f"%{q}%", limit),
    ).fetchall()
    conn.close()

    results = [
        HskCodeDetail(code=r[0], name_kr=r[1], name_en=r[2], level=r[3], parent_code=r[4], description=r[5])
        for r in rows
    ]
    return HskSearchResult(results=results, total=len(results))


@router.get("/hsk/{code}", response_model=HskCodeDetail)
async def get_hsk_code(code: str):
    settings = get_settings()
    conn = sqlite3.connect(settings.sqlite_db_path)
    cursor = conn.cursor()
    row = cursor.execute(
        "SELECT code, name_kr, name_en, level, parent_code, description FROM hsk_codes WHERE code = ?",
        (code,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="HSK 코드를 찾을 수 없습니다")

    children_rows = cursor.execute(
        "SELECT code, name_kr, name_en, level, parent_code, description FROM hsk_codes WHERE parent_code = ?",
        (code,),
    ).fetchall()
    conn.close()

    children = [
        HskCodeDetail(code=c[0], name_kr=c[1], name_en=c[2], level=c[3], parent_code=c[4], description=c[5])
        for c in children_rows
    ]
    return HskCodeDetail(
        code=row[0], name_kr=row[1], name_en=row[2], level=row[3],
        parent_code=row[4], description=row[5], children=children,
    )


@router.post("/data/refresh")
async def refresh_data(x_admin_key: str = Header(alias="X-Admin-Key")):
    settings = get_settings()
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="인증 실패")

    ensure_data_dirs(settings)
    crawler = HskCrawler()
    records = await crawler.fetch_all()
    crawler.save_to_sqlite(records, settings.sqlite_db_path)

    embedder = HskEmbedder(settings.openai_api_key, settings.chroma_db_path)
    embedder.embed_from_sqlite(settings.sqlite_db_path)

    return {"status": "ok", "records_count": len(records)}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `cd backend && python -m pytest tests/test_routes.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add backend/app/main.py backend/app/api/routes.py backend/tests/test_routes.py
git commit -m "feat: add FastAPI app with classify, hsk, and refresh endpoints"
```

---

## Task 10: React 프론트엔드 초기화

**Files:**
- Create: `frontend/` (Vite + React + TypeScript 프로젝트)

- [ ] **Step 1: Vite 프로젝트 생성**

```bash
cd 11_hscode-connector
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install axios react-router-dom
```

- [ ] **Step 2: vite.config.ts 수정**

```typescript
// frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 3: 커밋**

```bash
git add frontend/
git commit -m "chore: initialize React frontend with Vite"
```

---

## Task 11: API 클라이언트 및 타입 정의

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/types.ts`

- [ ] **Step 1: 타입 정의**

```typescript
// frontend/src/api/types.ts
export interface ClassifyRequest {
  description: string;
  top_n: number;
}

export interface ClassifyResult {
  rank: number;
  hsk_code: string;
  name_kr: string;
  name_en: string | null;
  confidence: number;
  reason: string;
}

export interface ClassifyResponse {
  results: ClassifyResult[];
  keywords_extracted: string[];
  processing_time_ms: number;
}

export interface HskCodeDetail {
  code: string;
  name_kr: string;
  name_en: string | null;
  level: number;
  parent_code: string | null;
  description: string | null;
  children: HskCodeDetail[];
}

export interface HskSearchResult {
  results: HskCodeDetail[];
  total: number;
}
```

- [ ] **Step 2: API 클라이언트**

```typescript
// frontend/src/api/client.ts
import axios from 'axios';
import type { ClassifyRequest, ClassifyResponse, HskCodeDetail, HskSearchResult } from './types';

const api = axios.create({ baseURL: '/api/v1' });

export async function classify(request: ClassifyRequest): Promise<ClassifyResponse> {
  const { data } = await api.post<ClassifyResponse>('/classify', request);
  return data;
}

export async function getHskCode(code: string): Promise<HskCodeDetail> {
  const { data } = await api.get<HskCodeDetail>(`/hsk/${code}`);
  return data;
}

export async function searchHsk(q: string, limit = 20): Promise<HskSearchResult> {
  const { data } = await api.get<HskSearchResult>('/hsk/search', { params: { q, limit } });
  return data;
}
```

- [ ] **Step 3: 커밋**

```bash
git add frontend/src/api/
git commit -m "feat: add API client and TypeScript types"
```

---

## Task 12: 메인 분류 페이지 (ClassifyPage)

**Files:**
- Create: `frontend/src/pages/ClassifyPage.tsx`
- Create: `frontend/src/components/ResultTable.tsx`

- [ ] **Step 1: ResultTable 컴포넌트**

```tsx
// frontend/src/components/ResultTable.tsx
import type { ClassifyResult } from '../api/types';

interface Props {
  results: ClassifyResult[];
  onCodeClick: (code: string) => void;
}

export default function ResultTable({ results, onCodeClick }: Props) {
  if (results.length === 0) return null;

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 16 }}>
      <thead>
        <tr>
          <th>순위</th>
          <th>HSK 코드</th>
          <th>품목명</th>
          <th>신뢰도</th>
          <th>선정 사유</th>
        </tr>
      </thead>
      <tbody>
        {results.map((r) => (
          <tr key={r.hsk_code} onClick={() => onCodeClick(r.hsk_code)} style={{ cursor: 'pointer' }}>
            <td>{r.rank}</td>
            <td style={{ fontFamily: 'monospace' }}>{r.hsk_code}</td>
            <td>{r.name_kr}{r.name_en ? ` (${r.name_en})` : ''}</td>
            <td>
              <div style={{ background: '#eee', borderRadius: 4, overflow: 'hidden', width: 100 }}>
                <div
                  style={{
                    width: `${r.confidence * 100}%`,
                    background: r.confidence > 0.7 ? '#4caf50' : r.confidence > 0.4 ? '#ff9800' : '#f44336',
                    height: 20,
                    textAlign: 'center',
                    color: '#fff',
                    fontSize: 12,
                    lineHeight: '20px',
                  }}
                >
                  {(r.confidence * 100).toFixed(0)}%
                </div>
              </div>
            </td>
            <td>{r.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 2: ClassifyPage**

```tsx
// frontend/src/pages/ClassifyPage.tsx
import { useState } from 'react';
import { classify } from '../api/client';
import type { ClassifyResponse } from '../api/types';
import ResultTable from '../components/ResultTable';

export default function ClassifyPage() {
  const [description, setDescription] = useState('');
  const [topN, setTopN] = useState(5);
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState('');
  const [response, setResponse] = useState<ClassifyResponse | null>(null);
  const [error, setError] = useState('');

  const handleSubmit = async () => {
    if (description.trim().length < 10) {
      setError('기술 설명은 최소 10자 이상이어야 합니다');
      return;
    }
    setLoading(true);
    setError('');
    setResponse(null);
    setStep('분류 처리 중...');
    try {
      const result = await classify({ description, top_n: topN });
      setResponse(result);
    } catch (e: any) {
      setError(e.response?.data?.detail || '분류 중 오류가 발생했습니다');
    } finally {
      setLoading(false);
      setStep('');
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: 24 }}>
      <h1>HSCode Connector</h1>
      <p>R&D 기술 설명을 입력하면 관련 HSK 코드를 찾아드립니다.</p>

      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="기술 설명을 입력하세요 (예: 리튬이온 배터리 양극재 제조를 위한 니켈 코발트 망간 합성 기술)"
        rows={5}
        style={{ width: '100%', fontSize: 14, padding: 8 }}
        maxLength={2000}
      />

      <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 16 }}>
        <label>
          Top N: {topN}
          <input
            type="range"
            min={1}
            max={20}
            value={topN}
            onChange={(e) => setTopN(Number(e.target.value))}
            style={{ marginLeft: 8 }}
          />
        </label>
        <button onClick={handleSubmit} disabled={loading} style={{ padding: '8px 24px' }}>
          {loading ? step : '분류하기'}
        </button>
      </div>

      {error && <p style={{ color: 'red', marginTop: 8 }}>{error}</p>}

      {response && (
        <>
          <p style={{ marginTop: 16, color: '#666' }}>
            추출된 키워드: {response.keywords_extracted.join(', ')} |
            처리 시간: {response.processing_time_ms}ms
          </p>
          <ResultTable results={response.results} onCodeClick={(code) => alert(`상세 보기: ${code}`)} />
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 3: App.tsx 수정**

```tsx
// frontend/src/App.tsx
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import ClassifyPage from './pages/ClassifyPage';
import BrowsePage from './pages/BrowsePage';

export default function App() {
  return (
    <BrowserRouter>
      <nav style={{ padding: '8px 24px', borderBottom: '1px solid #eee' }}>
        <Link to="/" style={{ marginRight: 16 }}>분류</Link>
        <Link to="/browse">HSK 탐색</Link>
      </nav>
      <Routes>
        <Route path="/" element={<ClassifyPage />} />
        <Route path="/browse" element={<BrowsePage />} />
      </Routes>
    </BrowserRouter>
  );
}
```

- [ ] **Step 4: 커밋**

```bash
git add frontend/src/
git commit -m "feat: add classify page with result table"
```

---

## Task 13: HSK 코드 탐색 페이지

**Files:**
- Create: `frontend/src/pages/BrowsePage.tsx`
- Create: `frontend/src/components/HskTree.tsx`

- [ ] **Step 1: HskTree 컴포넌트**

```tsx
// frontend/src/components/HskTree.tsx
import type { HskCodeDetail } from '../api/types';

interface Props {
  node: HskCodeDetail;
  onSelect: (code: string) => void;
}

export default function HskTree({ node, onSelect }: Props) {
  return (
    <div style={{ marginLeft: (node.level - 1) * 20, padding: '4px 0' }}>
      <span
        onClick={() => onSelect(node.code)}
        style={{ cursor: 'pointer', fontFamily: 'monospace' }}
      >
        {node.code}
      </span>
      {' '}{node.name_kr}
      {node.children?.map((child) => (
        <HskTree key={child.code} node={child} onSelect={onSelect} />
      ))}
    </div>
  );
}
```

- [ ] **Step 2: BrowsePage**

```tsx
// frontend/src/pages/BrowsePage.tsx
import { useState } from 'react';
import { searchHsk, getHskCode } from '../api/client';
import type { HskCodeDetail } from '../api/types';
import HskTree from '../components/HskTree';

export default function BrowsePage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<HskCodeDetail[]>([]);
  const [selected, setSelected] = useState<HskCodeDetail | null>(null);

  const handleSearch = async () => {
    if (!query.trim()) return;
    const data = await searchHsk(query);
    setResults(data.results);
    setSelected(null);
  };

  const handleSelect = async (code: string) => {
    const detail = await getHskCode(code);
    setSelected(detail);
  };

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: 24 }}>
      <h1>HSK 코드 탐색</h1>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="코드 또는 품목명 검색"
          style={{ flex: 1, padding: 8 }}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
        />
        <button onClick={handleSearch} style={{ padding: '8px 24px' }}>검색</button>
      </div>

      <div style={{ display: 'flex', gap: 24, marginTop: 16 }}>
        <div style={{ flex: 1 }}>
          {results.map((r) => (
            <div
              key={r.code}
              onClick={() => handleSelect(r.code)}
              style={{ padding: 8, cursor: 'pointer', borderBottom: '1px solid #eee' }}
            >
              <code>{r.code}</code> {r.name_kr}
            </div>
          ))}
        </div>
        {selected && (
          <div style={{ flex: 1, border: '1px solid #ddd', padding: 16, borderRadius: 8 }}>
            <h3>{selected.name_kr}</h3>
            <p>코드: <code>{selected.code}</code></p>
            {selected.name_en && <p>영문: {selected.name_en}</p>}
            {selected.description && <p>{selected.description}</p>}
            {selected.children.length > 0 && (
              <>
                <h4>하위 코드</h4>
                <HskTree node={selected} onSelect={handleSelect} />
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: 커밋**

```bash
git add frontend/src/pages/BrowsePage.tsx frontend/src/components/HskTree.tsx
git commit -m "feat: add HSK code browse page with tree view"
```

---

## Task 14: Docker Compose 및 PORT_REGISTRY 업데이트

**Files:**
- Create: `docker-compose.yml`
- Modify: `../PORT_REGISTRY.md`

- [ ] **Step 1: docker-compose.yml 작성**

```yaml
# docker-compose.yml
services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "${BACKEND_PORT:-8011}:8000"
    env_file:
      - ./backend/.env
    volumes:
      - ./data:/app/data
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "${FRONTEND_PORT:-8092}:80"
    depends_on:
      - backend
    restart: unless-stopped
```

- [ ] **Step 2: backend/Dockerfile 작성**

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: frontend/Dockerfile 작성**

```dockerfile
# frontend/Dockerfile
FROM node:20-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

- [ ] **Step 4: frontend/nginx.conf 작성**

```nginx
# frontend/nginx.conf
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

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

- [ ] **Step 5: PORT_REGISTRY.md 업데이트**

`../PORT_REGISTRY.md`의 "현재 사용 중인 포트 현황" 섹션에 추가:

```markdown
### 11_hscode-connector (R&D 기술 → HSK 코드 매핑)

| 서비스 | 호스트 포트 | 컨테이너 포트 | 기술 |
|--------|------------|--------------|------|
| backend | **8011**  | 8000         | FastAPI |
| frontend | **8092** | 80           | Nginx (정적 빌드) |
```

"전체 사용 포트 요약"에 추가:

```
8011        11_hscode-connector backend
8092        11_hscode-connector frontend (Nginx)
```

- [ ] **Step 6: 커밋**

```bash
git add docker-compose.yml backend/Dockerfile frontend/Dockerfile frontend/nginx.conf
git commit -m "feat: add Docker Compose with backend and frontend containers"
```

---

## Task 15: 통합 테스트 및 최종 검증

- [ ] **Step 1: 백엔드 전체 테스트 실행**

Run: `cd backend && python -m pytest -v`
Expected: 모든 테스트 PASS

- [ ] **Step 2: 프론트엔드 빌드 확인**

Run: `cd frontend && npm run build`
Expected: 빌드 성공, `dist/` 생성

- [ ] **Step 3: 로컬에서 백엔드 기동 확인**

Run: `cd backend && uvicorn app.main:app --port 8000`
Expected: 서버 기동, `/health` 응답 확인

- [ ] **Step 4: 최종 커밋**

```bash
git add -A
git commit -m "chore: finalize project setup and verify all tests pass"
```
