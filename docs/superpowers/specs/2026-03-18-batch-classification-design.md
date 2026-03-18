# 배치 분류 기능 설계서

## 개요

R&D 기술 설명을 엑셀 파일로 일괄 업로드하여 HSK 코드를 배치 매핑하고, 결과를 엑셀로 다운로드하는 기능.

- **비동기 처리**: 업로드 후 job_id를 받고, SSE로 진행률 확인, 완료 시 다운로드
- **Rate Limit 준수**: RPM 500, TPM 500,000 — Token Bucket 이중 버킷으로 제어
- **부분 실패 허용**: 건별 독립 처리, 실패 건만 재시도 가능

---

## 1. 전체 아키텍처

```
[사용자]
  │ 엑셀 업로드 (POST /api/v1/batch/upload)
  ▼
[BatchService] ── 엑셀 파싱 → 건별 작업 생성 → SQLite batch_jobs / batch_items 저장
  │                 job_id 반환
  ▼
[asyncio.Queue] ── 건별 작업을 큐에 투입
  │
  ▼
[BatchWorker (10개)] ── 큐에서 꺼내서 기존 ClassificationPipeline 호출
  │                      TokenBucketLimiter로 RPM/TPM 제어
  │                      결과/에러를 SQLite에 저장
  ▼
[SSE /api/v1/batch/{job_id}/progress] ── 프론트가 실시간 진행률 수신
  │
  ▼
[GET /api/v1/batch/{job_id}/download] ── 완료 시 결과 엑셀 다운로드
```

### 핵심 컴포넌트

| 컴포넌트 | 역할 |
|----------|------|
| `BatchService` | 엑셀 파싱, 작업 생성/조회, 결과 엑셀 생성 |
| `BatchWorker` | asyncio.Queue 소비자, 파이프라인 호출, 에러/재시도 |
| `TokenBucketLimiter` | RPM 500 / TPM 500,000 제한 관리 |
| `batch_routes.py` | 업로드, 진행률(SSE), 다운로드, 재시도 엔드포인트 |

---

## 2. SQLite 스키마

### batch_jobs (배치 작업 단위)

```sql
CREATE TABLE batch_jobs (
    job_id TEXT PRIMARY KEY,          -- UUID
    file_name TEXT NOT NULL,          -- 원본 파일명
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | processing | completed
    total_items INTEGER NOT NULL,
    completed_items INTEGER DEFAULT 0,
    failed_items INTEGER DEFAULT 0,
    top_n INTEGER DEFAULT 5,
    confidence_threshold REAL,        -- null이면 top_n 모드, 값 있으면 신뢰도 필터 모드
    model TEXT DEFAULT 'chatgpt-5.4-mini',
    created_at TEXT NOT NULL,
    completed_at TEXT
);
```

### batch_items (건별 처리 단위)

```sql
CREATE TABLE batch_items (
    item_id TEXT PRIMARY KEY,         -- UUID
    job_id TEXT NOT NULL REFERENCES batch_jobs(job_id),
    row_index INTEGER NOT NULL,       -- 엑셀 원본 행 번호
    task_name TEXT,                   -- 과제명 (선택)
    description TEXT NOT NULL,        -- 기술 설명
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | processing | completed | failed
    result_json TEXT,                 -- 분류 결과 JSON
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX idx_batch_items_job_id ON batch_items(job_id);
CREATE INDEX idx_batch_items_status ON batch_items(status);
```

---

## 3. Rate Limiting — Token Bucket

### 이중 Token Bucket 구조

RPM과 TPM을 각각 독립적인 버킷으로 관리. **LLM 호출과 임베딩 호출 모두** 동일한 버킷에서 관리 (OpenAI rate limit은 조직 단위로 모든 API 호출에 적용됨).

```
TokenBucketLimiter
├── RPM Bucket: capacity=400, refill=400/60초 (500의 80%)
└── TPM Bucket: capacity=400,000, refill=400,000/60초 (500,000의 80%)
```

### 동작 방식

1. **요청 전**: RPM 버킷에서 1토큰 소비 시도
2. **요청 전**: TPM 버킷에서 예상 토큰 수 사전 소비 (LLM ~1,500 / 임베딩 ~10)
3. **버킷 부족 시**: 충분히 채워질 때까지 `asyncio.sleep`으로 대기
4. **요청 후**: 실제 사용 토큰과 예상치 차이를 정산 (과다 소비분 반환)

### Rate Limit 적용 범위

모든 OpenAI API 호출이 TokenBucketLimiter를 통과해야 함:

| 호출 | 건당 횟수 | RPM 소비 | TPM 소비 |
|------|----------|---------|---------|
| 키워드 추출 (Chat) | 1회 | 1 | ~470 |
| 임베딩 (Embedding) | ~5회 | 5 | ~50 |
| 리랭킹 (Chat) | 1회 | 1 | ~950 |
| **건당 합계** | **~7회** | **7** | **~1,470** |

### 250건 예상 소요 시간

- 건당 OpenAI API 호출 ~7회 (LLM 2회 + 임베딩 ~5회)
- RPM 관점: 250 × 7 = 1,750 요청 → 분당 400 기준 **~4.4분** (rate limit 대기)
- TPM 관점: 250 × 1,470 = 367,500 토큰 → 분당 400,000 기준 ~0.9분 (병목 아님)
- **RPM이 병목**, 실제 처리 시간 포함: **약 5~7분**

---

## 4. BatchWorker & 에러 핸들링

### Worker 구조

```
[asyncio.Queue (maxsize=500)]
       │
       ├── Worker 1 ──┐
       ├── Worker 2 ──┤── 각 Worker가 큐에서 item을 꺼내
       ├── ...        ├── TokenBucket 통과 후
       └── Worker 10 ─┘── ClassificationPipeline 호출
```

- Worker 수: 동시 10개 (`asyncio.Task`)
- 파이프라인 인스턴스: 싱글턴으로 공유 (Worker 간 `ClassificationPipeline` 1개 공유, 내부 AsyncOpenAI 클라이언트 재사용)
- **Rate Limiter 주입**: `ClassificationPipeline.classify()`에 `rate_limiter` 파라미터 추가. 파이프라인이 각 서브서비스 호출 **전에** `await rate_limiter.acquire(rpm=1, tpm=예상토큰)` 호출로 외부에서 게이팅. 즉 KeywordExtractor/Reranker 내부는 변경하지 않고, pipeline.py에서 호출 직전에 rate limiter를 소비하는 방식. 단건 호출 시 `rate_limiter=None`이면 제한 없이 동작 (기존 동작 유지).
- 서버 시작 시 SQLite에서 미완료 작업 복원: `status=processing`인 항목은 `pending`으로 리셋 후 큐에 투입 (retry_count >= 3인 항목은 `failed`로 전환, max_retries는 상수 `MAX_RETRIES=3`으로 정의)

### 에러 핸들링 전략

| 에러 유형 | 처리 방식 |
|-----------|----------|
| OpenAI API 일시 에러 (429, 500, 503) | 자동 재시도, 최대 3회, 지수 백오프 (2s → 4s → 8s) |
| OpenAI API 영구 에러 (400, 401) | 즉시 실패 처리, 재시도 안 함|
| 파이프라인 타임아웃 (120초) | 실패 처리, 재시도 대상 |
| 건별 파싱 에러 (기술 설명 누락 등) | 즉시 실패, 에러 메시지 기록 |

### 부분 실패 처리

- 건별로 독립 처리 → 한 건의 실패가 다른 건에 영향 없음
- 실패 건은 `batch_items.status = 'failed'`, `error_message`에 사유 기록
- 모든 건이 완료/실패되면 `batch_jobs.status`를 `completed`로 변경 (실패 건이 있어도)
- 재시도 엔드포인트: `POST /api/v1/batch/{job_id}/retry` → 실패 건만 status를 pending으로 복귀, 큐에 재투입

### 작업 상태 전이

```
batch_jobs:  pending → processing → completed
batch_items: pending → processing → completed
                                  → failed (retry 시 → pending으로 복귀)
```

---

## 5. 엑셀 입출력 포맷

### 입력 템플릿

| 열 | 필드명 | 필수 | 설명 |
|----|--------|------|------|
| A | 과제명 | 선택 | 식별용 (결과에 그대로 반영) |
| B | 기술설명 | **필수** | 10~2,000자 |

- 1행은 헤더, 2행부터 데이터
- 빈 행은 자동 건너뜀
- 기술설명이 비어있거나 10자 미만이면 해당 건 즉시 실패 처리
- **최대 행 수 제한: 500건** — 초과 시 업로드 거부 (에러 메시지 반환)

### 출력 — 시트 1: 요약

필터링 모드에 따라 HSK 코드 열이 동적으로 생성됨.

**공통 열:**

| 열 | 필드 |
|----|------|
| A | 과제명 |
| B | 기술설명 |
| C | 상태 (성공/실패) |
| D | 추출 키워드 |

**동적 열 (E열부터):**

- **top_n 모드**: `HSK코드_1`, `HSK코드_2`, ..., `HSK코드_N` (고정 N개, 부족하면 빈 셀)
- **신뢰도 모드**: `HSK코드_1`, `HSK코드_2`, ..., `HSK코드_M` (전체 결과 중 최대 개수에 맞춰 열 생성, 건마다 해당되는 수만큼 채움, **최대 20개 상한**)

### 출력 — 시트 2: 상세

| 열 | 필드 |
|----|------|
| A | 과제명 |
| B | 기술설명 |
| C | 순위 |
| D | HSK코드 (포맷: XXXX.XX-XXXX) |
| E | 품목명(한) |
| F | 품목명(영) |
| G | 신뢰도 (%) |
| H | 선정 사유 |

- 기술 1건당 결과 수만큼 행 생성
- 실패 건은 상세 시트에 C열="에러", H열=에러 메시지

---

## 6. API 엔드포인트

| Method | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/batch/template` | 빈 템플릿 엑셀 다운로드 |
| POST | `/api/v1/batch/upload` | 엑셀 업로드, 배치 작업 생성 |
| GET | `/api/v1/batch/{job_id}/progress` | SSE 실시간 진행률 |
| GET | `/api/v1/batch/{job_id}/download` | 결과 엑셀 다운로드 |
| POST | `/api/v1/batch/{job_id}/retry` | 실패 건 재시도 |
| GET | `/api/v1/batch/jobs` | 작업 목록 조회 |

### POST /api/v1/batch/upload

```
Content-Type: multipart/form-data

file: (엑셀 파일)
top_n: 5                    (선택, 기본값 5)
confidence_threshold: null  (선택, 설정 시 신뢰도 모드)
model: "chatgpt-5.4-mini"  (선택)
```

- `confidence_threshold`가 설정되면 신뢰도 모드, 아니면 top_n 모드
- 두 값이 동시에 있으면 `confidence_threshold` 우선

### confidence_threshold 처리 흐름

1. BatchWorker가 `ClassificationPipeline.classify()`를 `top_n=20`(max)으로 호출하여 최대 결과를 확보
2. 반환된 결과에서 `confidence >= threshold`인 것만 필터링
3. 필터링된 결과를 `batch_items.result_json`에 저장
4. 이 방식은 파이프라인 내부 변경 없이 후처리로 구현 가능

### SSE 진행률 메시지 형식

```json
{"type": "progress", "completed": 45, "failed": 2, "total": 250, "percent": 18.8}
{"type": "item_done", "row_index": 46, "status": "completed", "hsk_code_1": "8507.60-1000"}
{"type": "complete", "completed": 243, "failed": 7, "total": 250}
```

---

## 7. 프론트엔드

### ClassifyPage 탭 추가

기존 ClassifyPage에 **"단건 | 배치"** 탭 전환 추가.

### 배치 탭 UI 구성

1. **설정 영역**
   - 필터링 모드 토글: "상위 N개" / "신뢰도 기준"
   - top_n 또는 신뢰도(%) 입력
   - 모델 선택 (기존과 동일)

2. **업로드 영역**
   - 템플릿 다운로드 버튼
   - 파일 드래그앤드롭 또는 클릭 업로드
   - 업로드 전 파일 미리보기 (건수, 첫 3행)

3. **진행률 영역** (업로드 후 표시)
   - 프로그레스 바 (완료/실패/전체)
   - 실시간 처리 현황 테이블 (행번호, 상태, 1순위 코드)
   - 예상 남은 시간

4. **결과 영역** (완료 후 표시)
   - 요약: 성공 N건, 실패 N건
   - 결과 엑셀 다운로드 버튼
   - 실패 건이 있으면 "실패 건 재시도" 버튼

---

## 8. 파일 구조

### Backend 신규

| 파일 | 역할 |
|------|------|
| `app/api/batch_routes.py` | 배치 전용 엔드포인트 6개 |
| `app/services/batch_service.py` | 엑셀 파싱, 작업 CRUD, 결과 엑셀 생성 |
| `app/services/batch_worker.py` | asyncio.Queue Worker, 작업 소비/처리 |
| `app/services/rate_limiter.py` | TokenBucketLimiter (RPM/TPM 이중 버킷) |
| `app/data/batch_db.py` | batch_jobs, batch_items 테이블 생성/쿼리 |

### Backend 수정

| 파일 | 변경 내용 |
|------|----------|
| `app/main.py` | batch_routes 등록, 서버 시작 시 Worker 기동 & 미완료 작업 복원, 파이프라인 싱글턴 |
| `app/services/vector_search.py` | AsyncOpenAI 전환, ChromaDB `to_thread` 래핑, `search()` async 변경 |
| `app/core/pipeline.py` | `search()` 호출에 `await` 추가 |

### Frontend 수정

| 파일 | 변경 내용 |
|------|----------|
| `src/pages/ClassifyPage.tsx` | 탭 UI 추가 (단건/배치 전환) |
| `src/api/client.ts` | 배치 관련 API 함수 추가 |
| `src/api/types.ts` | 배치 관련 타입 추가 |

### Frontend 신규

| 파일 | 역할 |
|------|------|
| `src/components/BatchTab.tsx` | 배치 탭 전체 UI (설정, 업로드, 진행률, 결과) |

---

## 9. VectorSearchService 비동기 전환

기존 `VectorSearchService`는 동기 `OpenAI` 클라이언트와 동기 ChromaDB 호출을 사용. 배치 처리를 위해 전면 async로 전환.

### 변경 사항

1. **OpenAI 클라이언트**: `OpenAI` → `AsyncOpenAI`로 변경 (임베딩 호출도 async)
2. **ChromaDB 호출**: `asyncio.to_thread`로 래핑 (ChromaDB는 async 미지원)
3. **`search()` 메서드**: `def search()` → `async def search()`
4. **임베딩 호출에 TokenBucketLimiter 적용**: rate limiter를 주입받아 임베딩 호출 전 RPM/TPM 소비

```python
# 변경 후 search() 시그니처
async def search(self, keywords: list[str], limit: int = 50,
                 threshold: float = 1.5, rate_limiter: TokenBucketLimiter | None = None) -> list[SearchCandidate]:
```

### pipeline.py 수정

`ClassificationPipeline.classify()` 내에서 `search()` 호출을 `await`로 변경:

```python
# 기존
candidates = self.vector_search.search(keywords, ...)

# 변경
candidates = await self.vector_search.search(keywords, ...)
```

기존 단건 파이프라인에서는 `rate_limiter=None`으로 호출하여 rate limiting 없이 동작 (기존 동작 유지).

---

## 10. SQLite 동시 쓰기 처리

10개 Worker가 동시에 결과를 쓰므로 SQLite 동시 쓰기 충돌 방지 필요.

- **WAL 모드 활성화**: `PRAGMA journal_mode=WAL` — 읽기/쓰기 동시 가능
- **단일 Writer 패턴**: `batch_db.py`에서 `asyncio.Lock`으로 쓰기 직렬화
- 기존 `hsk.db`와 별도 DB 파일(`batch.db`)을 사용하여 간섭 최소화

---

## 11. SSE 연결 관리

- **재접속 시**: 현재 job 상태(completed/failed/total)를 즉시 전송 후 이후 이벤트 스트리밍
- **완료 후**: `complete` 이벤트 전송 후 연결 종료
- **Heartbeat**: 15초 간격 `{"type": "heartbeat"}` 전송 (Nginx proxy timeout 방지)
- **Nginx 설정**: `proxy_buffering off`, `proxy_read_timeout 600s` 추가 필요

---

## 12. 동시 작업 정책

- 동시에 여러 배치 작업 업로드 가능
- 모든 작업의 item이 단일 asyncio.Queue에 FIFO로 투입
- 공정성: 별도 우선순위 없이 투입 순서대로 처리 (선착순)
