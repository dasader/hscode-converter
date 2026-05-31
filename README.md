# HSCode Connector

R&D 기술 설명을 입력하면 관세청 HSK(관세·통계통합품목분류표) 10자리 코드를 AI가 자동 매핑해주는 시스템.  
Google Gemini 기반 3단계 RAG 파이프라인(키워드 추출 → 벡터 검색 → 리랭킹)으로 동작한다.

## 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | FastAPI, Python 3.12 |
| Frontend | React 19, TypeScript, Vite |
| LLM / Embedding | Google Gemini (`gemini-3.5-flash` / `gemini-embedding-001`) |
| Vector DB | ChromaDB (cosine similarity, 1536D) |
| RDB | SQLite |
| 배포 | Docker Compose, Nginx |

## 주요 기능

- **단일 분류**: 기술 설명(10~2,000자) 입력 → HSK 코드 + 신뢰도(0~100%) + 선정 사유 (SSE 스트리밍)
- **배치 분류**: Excel 파일 업로드(최대 500행) → 일괄 처리 → 결과 Excel 다운로드
- **HSK 브라우저**: 코드·품목명(한/영) 검색 및 계층 트리(류→호→소호→통계부호→HSK) 탐색

## 실행 방법

### 환경변수 설정

`backend/.env` 파일을 생성한다:

```env
GOOGLE_API_KEY=your-gemini-api-key
ADMIN_API_KEY=your-admin-key
```

### 관세청 데이터 준비

`data/` 폴더에 관세청 HSK 엑셀 파일을 넣는다. 지원 형식:

- `관세청_HSK별 신성질별_성질별 분류_YYYYMMDD.xlsx` (신형식 — 계층 분류 포함)
- `관세청_HS부호_YYYYMMDD.xlsx` (구형식)

### Docker Compose (권장)

```bash
docker compose up -d --build
```

서버 시작 시 엑셀 파싱 및 Gemini 임베딩 생성이 자동으로 시작된다 (수 분 소요).

```bash
docker compose logs -f backend   # 진행 상황 실시간 확인
```

- Frontend: http://localhost:8092
- Backend API: http://localhost:8011

### 로컬 개발

```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

- Frontend (dev): http://localhost:5180
- Backend (dev): http://localhost:8000

## 파이프라인 흐름

```
기술 설명 입력
  ↓
1. 키워드 추출 (Gemini)   — 제품·물질·부품·장비 키워드 추출
  ↓
2. 벡터 검색 (ChromaDB)   — 키워드 임베딩 후 cosine 유사도로 후보 50개 선별
  ↓
3. 리랭킹 (Gemini)        — 신뢰도 점수 및 선정 사유와 함께 최종 결과 반환
```

## API 주요 엔드포인트

| Method | 경로 | 설명 |
|--------|------|------|
| POST | `/api/v1/classify` | 단일 분류 (JSON) |
| POST | `/api/v1/classify/stream` | 단일 분류 (SSE 스트리밍) |
| GET | `/api/v1/hsk/search?q=` | HSK 코드/품목명 검색 |
| GET | `/api/v1/hsk/{code}` | HSK 코드 상세 + 계층 조회 |
| POST | `/api/v1/data/refresh` | 데이터 갱신 (Admin 인증 필요) |
| GET | `/api/v1/data/status` | 데이터 로드 상태 확인 |
| POST | `/api/v1/batch/upload` | 배치 Excel 업로드 |
| GET | `/api/v1/batch/{job_id}/progress` | 배치 진행 상황 (SSE) |

### 분류 요청 예시

```bash
curl -X POST http://localhost:8011/api/v1/classify \
  -H "Content-Type: application/json" \
  -d '{
    "description": "리튬이온 배터리 양극재 제조를 위한 니켈 코발트 망간 합성 기술",
    "top_n": 5
  }'
```

### 응답 예시

```json
{
  "results": [
    {
      "rank": 1,
      "hsk_code": "8507.60-1000",
      "name_kr": "리튬이온 축전지",
      "name_en": "Lithium-ion accumulators",
      "confidence": 0.95,
      "reason": "양극재 합성 기술은 리튬이온 배터리 핵심 소재 제조에 해당"
    }
  ],
  "keywords_extracted": ["양극재", "리튬이온 배터리", "NCM"],
  "processing_time_ms": 3450
}
```

## 테스트

```bash
cd backend && pytest -v
```

대부분의 테스트가 실제 Gemini API를 호출하므로 `GOOGLE_API_KEY` 환경변수가 필요하다.

## 포트 구성

| 서비스 | 호스트 포트 | 컨테이너 포트 |
|--------|------------|-------------|
| Backend (FastAPI) | 8011 | 8000 |
| Frontend (Nginx) | 8092 | 80 |
| Frontend (Vite dev) | 5180 | 5173 |

## 반쪽 임베딩 복구

임베딩 도중 서버 오류로 중단된 경우:

```bash
rm -rf ./data/chromadb
docker compose up -d --build
```

SQLite 데이터는 보존된 채 임베딩만 처음부터 재생성된다.
