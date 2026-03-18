# HSCode Connector

R&D 기술 설명을 입력하면 관련 HSK(관세·통계통합품목분류표) 10자리 코드를 AI가 매핑해주는 시스템입니다.

## 주요 기능

### 기술 분류 (Technology Classification)

- R&D 기술 설명(10~2,000자)을 입력하면 관련 HSK 코드를 추천
- 3단계 RAG 파이프라인으로 처리:
  1. **키워드 추출** — GPT가 기술 설명에서 제품·물질·부품·장비 키워드를 추출
  2. **벡터 검색** — 키워드별 임베딩 생성 후 ChromaDB에서 유사 HSK 코드 후보 검색
  3. **리랭킹** — GPT가 후보 중 최종 코드를 선정하고 신뢰도·사유를 제시
- 결과 건수(3~20개), 신뢰도 임계값, 모델(Nano/Mini/Standard) 선택 가능
- 각 결과에 신뢰도 점수(0~100%)와 선정 사유 표시

### 코드 탐색 (Code Browse)

- HSK 코드 또는 품목명(한/영)으로 검색
- 코드 선택 시 상세 정보 및 계층 구조(류→호→소호→통계부호→HSK) 트리 탐색
- 상위/하위 코드 간 자유로운 네비게이션

### 데이터 관리

- 서버 시작 시 `data/` 디렉터리의 관세청 엑셀 파일을 자동 로드
- SQLite에 코드 저장, ChromaDB에 벡터 임베딩 자동 생성
- Admin API를 통한 데이터 갱신 지원
- 데이터 로드 상태를 프론트엔드에서 실시간 확인

## 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | FastAPI, Python 3.12 |
| Frontend | React 19, TypeScript, Vite |
| LLM | OpenAI GPT (키워드 추출 + 리랭킹) |
| Embedding | OpenAI text-embedding-3-small |
| Vector DB | ChromaDB (cosine similarity) |
| RDB | SQLite |
| 배포 | Docker Compose, Nginx |

## 프로젝트 구조

```
11_hscode-connector/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 앱, 시작 시 자동 데이터 로드
│   │   ├── api/routes.py        # API 엔드포인트
│   │   ├── core/
│   │   │   ├── config.py        # 환경변수 설정
│   │   │   └── pipeline.py      # 3단계 분류 파이프라인
│   │   ├── services/
│   │   │   ├── keyword_extractor.py  # GPT 키워드 추출
│   │   │   ├── vector_search.py      # ChromaDB 벡터 검색
│   │   │   └── reranker.py           # GPT 리랭킹
│   │   ├── data/
│   │   │   ├── crawler.py       # 엑셀 → SQLite 로더
│   │   │   └── embedder.py      # SQLite → ChromaDB 임베딩
│   │   └── models/schemas.py    # Pydantic 스키마
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # 라우팅 (분류 / 탐색)
│   │   ├── pages/
│   │   │   ├── ClassifyPage.tsx # 기술 분류 페이지
│   │   │   └── BrowsePage.tsx   # 코드 탐색 페이지
│   │   ├── components/
│   │   │   ├── ResultTable.tsx  # 분류 결과 테이블
│   │   │   └── HskTree.tsx     # 계층 트리 컴포넌트
│   │   └── api/
│   │       ├── client.ts        # Axios API 클라이언트
│   │       └── types.ts         # TypeScript 인터페이스
│   ├── nginx.conf
│   └── Dockerfile
├── data/                        # 관세청 엑셀, SQLite, ChromaDB 데이터
├── docker-compose.yml
└── README.md
```

## 실행 방법

### 환경변수 설정

`backend/.env` 파일을 생성합니다:

```env
OPENAI_API_KEY=sk-your-api-key
ADMIN_API_KEY=your-admin-key
CHROMA_DB_PATH=./data/chromadb
SQLITE_DB_PATH=./data/hsk.db
```

### Docker Compose (권장)

```bash
docker-compose up --build
```

- Frontend: http://localhost:8092
- Backend API: http://localhost:8011

### 로컬 개발

**Backend:**
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

- Frontend (dev): http://localhost:5180
- Backend: http://localhost:8000

### 데이터 준비

`data/` 디렉터리에 관세청 HSK 엑셀 파일을 배치합니다. 지원 형식:

- `관세청_HSK별 신성질별_성질별 분류_YYYYMMDD.xlsx` (신형식 — 계층 분류 포함)
- `관세청_HS부호_YYYYMMDD.xlsx` (구형식)

서버 시작 시 자동으로 로드 및 임베딩을 생성합니다.

## API 엔드포인트

| Method | 경로 | 설명 |
|--------|------|------|
| POST | `/api/v1/classify` | 기술 설명 → HSK 코드 분류 |
| GET | `/api/v1/hsk/search?q=&limit=` | HSK 코드/품목명 검색 |
| GET | `/api/v1/hsk/{code}` | HSK 코드 상세 + 계층 조회 |
| POST | `/api/v1/data/refresh` | 데이터 갱신 (Admin 인증 필요) |
| GET | `/api/v1/data/sources` | 데이터 출처 이력 |
| GET | `/api/v1/data/status` | 데이터 로드 상태 |
| GET | `/health` | 서버 상태 확인 |

### 분류 요청 예시

```bash
curl -X POST http://localhost:8011/api/v1/classify \
  -H "Content-Type: application/json" \
  -d '{
    "description": "리튬이온 배터리 양극재 제조를 위한 니켈 코발트 망간 합성 기술",
    "top_n": 5,
    "model": "chatgpt-5.4-mini"
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
  "keywords_extracted": ["양극재", "cathode material", "리튬이온 배터리", "NCM"],
  "processing_time_ms": 3450
}
```

## 포트 구성

| 서비스 | 컨테이너 포트 | 호스트 포트 |
|--------|-------------|------------|
| Backend (FastAPI) | 8000 | 8011 |
| Frontend (Nginx) | 80 | 8092 |
| Frontend (Vite dev) | 5173 | 5180 |

## 테스트

```bash
cd backend
pytest -v
```
