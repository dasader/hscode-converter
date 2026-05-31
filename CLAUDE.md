# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

R&D 기술 설명 → HSK(관세청 품목분류) 10자리 코드 매핑 시스템. 3단계 RAG 파이프라인으로 동작한다.

- **Backend**: FastAPI + Google Gemini + ChromaDB + SQLite
- **Frontend**: React 19 + TypeScript + Vite

## 포트

| 서비스 | 호스트 | 컨테이너 |
|--------|--------|---------|
| Backend (FastAPI) | 8011 | 8000 |
| Frontend (Nginx prod) | 8092 | 80 |
| Frontend (Vite dev) | 5180 | 5173 |

## 명령어

```bash
# Backend 개발 서버
cd backend && uvicorn app.main:app --reload --port 8000

# Frontend 개발 서버
cd frontend && npm run dev

# 전체 테스트
cd backend && pytest -v

# 특정 테스트 파일만
cd backend && pytest tests/test_pipeline.py -v

# Docker 전체 스택
docker compose up -d --build

# 실시간 로그
docker compose logs -f backend
```

## RAG 파이프라인 아키텍처

`ClassificationPipeline.classify()` 안에서 3단계가 순차 실행된다.

```
사용자 입력 (기술 설명)
  ↓
1. KeywordExtractor      — Gemini로 제품/물질/부품 키워드 추출
  ↓
2. VectorSearchService   — 키워드별 Gemini 임베딩(1536D) → ChromaDB cosine 검색 → 후보 50개
  ↓
3. Reranker              — Gemini로 후보 재정렬 + 신뢰도(0~1) + 사유 생성 → top_n 반환
```

`/api/v1/classify/stream` 엔드포인트는 각 단계를 SSE로 실시간 전송한다.

## 서버 시작 시 자동 데이터 로드 (`main.py`)

앱 시작 시 백그라운드 스레드(`_auto_load_sync`)가 실행된다:

1. `data/` 폴더에서 최신 `.xlsx`(관세청 HSK 엑셀) 탐지
2. SQLite(`hsk.db`)에 데이터가 없으면 → `HskCrawler`로 파싱 후 저장
3. ChromaDB에 임베딩이 없거나 불완전(SQLite level-5 count 대비 90% 미만)이면 → `HskEmbedder`로 생성
4. 서버 재시작 시 미완료 배치 작업 자동 복원

`/api/v1/data/status`로 현재 상태(`idle` / `loading` / `embedding` / `ready` / `error`) 확인 가능.

## 데이터 계층

- **`app/data/crawler.py`** — Excel → SQLite. 코드 포맷: `8507601000` → `8507.60-1000`. 계층(2→4→6→8→10자리) 및 부모 관계 파악.
- **`app/data/embedder.py`** — SQLite → ChromaDB. 100건씩 배치 처리. 임시 컬렉션(`hsk_codes_tmp`)에 먼저 기록 후 성공 시 `hsk_codes`로 교체(원본 보호). 503/429 에러 시 지수 백오프 재시도(최대 5회, 최대 60초).
- **`app/data/batch_db.py`** — 배치 작업 SQLite(`batch.db`). WAL 모드 + 스레드 락.

## 배치 처리

`BatchWorker` — 비동기 큐 기반, 기본 5개 워커. 아이템당 API 에러/타임아웃 발생 시 지수 백오프 재시도(최대 3회). `BatchService`가 Excel 업로드(최대 500행) 및 결과 다운로드(요약 + 상세 시트 2개)를 담당.

## 설정 (`app/core/config.py`)

Pydantic Settings로 관리. `.env` 파일 필요.

| 키 | 기본값 | 설명 |
|----|--------|------|
| `GOOGLE_API_KEY` | 필수 | Gemini API 키 |
| `ADMIN_API_KEY` | 필수 | 데이터 갱신 엔드포인트 인증 |
| `GEMINI_MODEL` | `gemini-3.5-flash` | 분류용 모델 |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | 임베딩 모델 |
| `PIPELINE_TIMEOUT` | `120` | 전체 파이프라인 타임아웃(초) |
| `MAX_TOP_N` | `30` | 최대 결과 수 |
| `SIMILARITY_THRESHOLD` | `1.5` | cosine distance 임계값 |

## 주요 API 엔드포인트

| 경로 | 설명 |
|------|------|
| `POST /api/v1/classify` | 단일 분류 |
| `POST /api/v1/classify/stream` | 단일 분류 (SSE) |
| `GET /api/v1/data/status` | 데이터 로드 상태 |
| `POST /api/v1/data/refresh` | 강제 재로드 (Admin 인증) |
| `POST /api/v1/batch/upload` | 배치 Excel 업로드 |
| `GET /api/v1/batch/{job_id}/progress` | 배치 진행 (SSE) |
| `POST /api/v1/batch/{job_id}/retry` | 실패 항목 재시도 |

## 테스트 구조

`backend/tests/`에 서비스별 단위 테스트와 통합 테스트(`test_pipeline.py`, `test_routes.py`)가 있다. 대부분의 테스트가 실제 Gemini API를 호출하므로 `GOOGLE_API_KEY` 환경변수 필요.

## 반쪽 임베딩 복구 방법

원격 서버에서 503으로 임베딩이 중단된 경우:

```bash
rm -rf ./data/chromadb
docker compose up -d --build
```

`chromadb`만 삭제하면 SQLite는 보존된 채 재임베딩만 자동 실행된다.
