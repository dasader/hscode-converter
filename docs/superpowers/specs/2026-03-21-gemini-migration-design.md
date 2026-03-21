# OpenAI → Gemini 마이그레이션 설계

## 개요

RAG 파이프라인의 LLM/임베딩 백엔드를 OpenAI에서 Google Gemini로 전면 교체한다.

- 키워드 추출 + 리랭킹: `gemini-3-flash-preview` (환경변수로 변경 가능)
- 임베딩: `gemini-embedding-001`, 1536차원 (환경변수로 변경 가능)
- SDK: `google-genai` (공식 Python SDK)
- 모델 선택 UI 제거 (서버 환경변수로 관리)

## 환경변수

```env
# 기존
OPENAI_API_KEY=sk-xxx

# 변경
GOOGLE_API_KEY=AIza-xxx
GEMINI_MODEL=gemini-3-flash-preview
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
```

## 변경 파일 목록

### Backend (14개)

| 파일 | 변경 내용 |
|------|----------|
| `requirements.txt` | `openai==1.58.1` → `google-genai` |
| `.env.example` | `OPENAI_API_KEY` → `GOOGLE_API_KEY`, `GEMINI_MODEL`, `GEMINI_EMBEDDING_MODEL` 추가 |
| `app/core/config.py` | `openai_api_key` → `google_api_key`, `gemini_model`, `gemini_embedding_model` 추가 |
| `app/core/pipeline.py` | `classify()`에서 `model` 파라미터 제거, 하위 서비스 호출에서 `model` 전달 제거 |
| `app/services/keyword_extractor.py` | AsyncOpenAI → google-genai, MODEL_MAP 제거, 생성자에서 `model` 받음 |
| `app/services/reranker.py` | 동일 패턴으로 전환, 생성자에서 `model` 받음 (temperature=0.1 유지) |
| `app/services/vector_search.py` | 임베딩 → gemini-embedding-001 (1536차원), 생성자에서 `model` 받음 |
| `app/data/embedder.py` | 동기 OpenAI → google-genai, 생성자에서 `model` 받음, 1536차원 |
| `app/services/batch_worker.py` | 에러 클래스 교체, `model = job["model"]` 제거 |
| `app/api/routes.py` | 서비스 초기화 시 `settings.google_api_key` + 모델명 전달, `model` 파라미터 제거 |
| `app/api/batch_routes.py` | `model` Form 파라미터 제거 |
| `app/main.py` | `openai_api_key` → `google_api_key` 참조 변경 |
| `app/models/schemas.py` | `ClassifyRequest`에서 `model` 필드 제거 |
| `app/data/batch_db.py` | `create_job()`에서 `model` 파라미터 제거, 테이블 기본값 변경 |
| `app/services/batch_service.py` | `create_job()`에서 `model` 파라미터 제거 |

### Frontend (5개)

| 파일 | 변경 내용 |
|------|----------|
| `pages/ClassifyPage.tsx` | MODEL_OPTIONS, model state, 모델 선택 UI 제거 |
| `pages/ClassifyPage.css` | `.model-control`, `.model-selector` CSS 제거 |
| `components/BatchTab.tsx` | MODEL_OPTIONS, model state, 모델 선택 UI 제거 |
| `api/types.ts` | `ClassifyRequest.model`, `BatchJob.model` 필드 제거 |
| `api/client.ts` | `uploadBatch()`에서 model 파라미터 제거 |

### Tests (6개)

| 파일 | 변경 내용 |
|------|----------|
| `tests/test_config.py` | `OPENAI_API_KEY` → `GOOGLE_API_KEY` |
| `tests/test_keyword_extractor.py` | mock 대상을 google-genai로 변경 |
| `tests/test_reranker.py` | mock 대상을 google-genai로 변경 |
| `tests/test_vector_search.py` | mock 대상을 google-genai로 변경 |
| `tests/test_pipeline.py` | `classify()` 호출에서 `model` 제거 |
| `tests/test_batch_worker.py` | `create_job()` 호출에서 `model` 제거, 에러 클래스 변경 |
| `tests/test_batch_routes.py` | `OPENAI_API_KEY` → `GOOGLE_API_KEY`, model 관련 제거 |

## 서비스 초기화 흐름

모델명이 `config.py` → 각 서비스 생성자로 전달되는 흐름:

```python
# routes.py: get_pipeline()
settings = Settings()

pipeline = ClassificationPipeline(
    keyword_extractor=KeywordExtractor(settings.google_api_key, settings.gemini_model),
    vector_search=VectorSearchService(settings.google_api_key, settings.chroma_db_path, settings.gemini_embedding_model),
    reranker=Reranker(settings.google_api_key, settings.gemini_model),
    ...
)

# main.py: embedder 초기화
embedder = HskEmbedder(settings.google_api_key, settings.chroma_db_path, settings.gemini_embedding_model)
```

각 서비스 생성자:
```python
class KeywordExtractor:
    def __init__(self, api_key: str, model: str):
        self.client = genai.Client(api_key=api_key)
        self.model = model

class Reranker:
    def __init__(self, api_key: str, model: str):
        self.client = genai.Client(api_key=api_key)
        self.model = model

class VectorSearchService:
    def __init__(self, api_key: str, chroma_db_path: str, embedding_model: str):
        self.client = genai.Client(api_key=api_key)
        self.embedding_model = embedding_model

class HskEmbedder:
    def __init__(self, api_key: str, chroma_db_path: str, embedding_model: str):
        self.client = genai.Client(api_key=api_key)
        self.embedding_model = embedding_model
```

## API 호출 패턴

### Chat — 키워드 추출 (temperature=0.2)

```python
response = await self.client.aio.models.generate_content(
    model=self.model,
    contents=prompt,
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.2,
        response_mime_type="application/json",
    ),
)
raw = response.text
```

### Chat — 리랭킹 (temperature=0.1)

```python
response = await self.client.aio.models.generate_content(
    model=self.model,
    contents=user_prompt,
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.1,
        response_mime_type="application/json",
    ),
)
raw = response.text
```

- `response_mime_type="application/json"` — 네이티브 JSON 모드
- 폴백 파싱(`parse_keywords`, `parse_response`)은 안전을 위해 유지

### 임베딩 (쿼리 타임, 비동기)

```python
response = await self.client.aio.models.embed_content(
    model=self.embedding_model,
    contents=text,
    config=types.EmbedContentConfig(output_dimensionality=1536),
)
return list(response.embeddings[0].values)
```

### 임베딩 (초기 벡터화, 동기 배치)

```python
response = self.client.models.embed_content(
    model=self.embedding_model,
    contents=texts,  # list[str]
    config=types.EmbedContentConfig(output_dimensionality=1536),
)
return [list(e.values) for e in response.embeddings]
```

### 에러 처리

```python
from google.api_core.exceptions import ResourceExhausted, InternalServerError, ServiceUnavailable

RETRYABLE_ERRORS = (ResourceExhausted, InternalServerError, ServiceUnavailable, asyncio.TimeoutError)
```

## 파이프라인 인터페이스 변경

`model` 파라미터를 파이프라인 호출 체인 전체에서 제거:

```python
# 기존
pipeline.classify(description, top_n=5, model="chatgpt-5.4-mini")
keyword_extractor.extract(description, model=model)
reranker.rerank(description, candidates, top_n, model=model)

# 변경
pipeline.classify(description, top_n=5)
keyword_extractor.extract(description)
reranker.rerank(description, candidates, top_n)
```

## batch_db.py model 컬럼 처리

- `create_job()`에서 `model` 파라미터 제거
- INSERT 시 `model` 컬럼에 값을 넣지 않음 (기존 `DEFAULT 'chatgpt-5.4-mini'` → 불필요하지만 스키마는 유지)
- 기존 완료된 작업의 하위호환을 위해 **테이블 컬럼은 삭제하지 않음** (SQLite ALTER TABLE DROP COLUMN 제약도 있음)
- `batch_worker.py`에서 `model = job["model"]` 라인 제거

## 임베딩 재생성

OpenAI와 Gemini의 벡터 공간이 다르므로 기존 ChromaDB 데이터와 호환 불가.

**배포 절차:**
1. 기존 ChromaDB 폴더(`./data/chromadb`) 삭제
2. 새 환경변수(`.env`) 설정
3. 서버 재시작 → `_auto_load_sync()`에서 자동 재임베딩

또는 `/api/v1/data/refresh` API 호출로 재생성 가능.

## Rate Limiting

유료 티어 RPM 1,000이므로 현재 `TokenBucketLimiter` 구조를 유지하되, 기존 설정(rpm=500, tpm=500000)을 그대로 사용. `pipeline.py`의 TPM 추정값(470, 950)도 유지 — Gemini 토큰 카운팅이 OpenAI와 다를 수 있으나, 안전 마진이 충분하므로 초기에는 그대로 사용하고 필요 시 조정.
