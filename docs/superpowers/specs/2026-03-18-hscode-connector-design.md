# HSCode Connector 설계 문서

**날짜:** 2026-03-18
**상태:** 승인됨

## 1. 개요

R&D 기술 설명(자연어)을 입력하면 관련 HSK 10자리 코드를 관련도 순으로 제시하는 시스템.

### 핵심 과제

R&D 기술 설명은 "기술"을 서술하지만, HS 코드는 "무역 상품"을 분류한다. 이 간극을 LLM 기반 RAG 파이프라인으로 해결한다.

### 요구사항

| 항목 | 내용 |
|------|------|
| 입력 | 자연어 R&D 기술 설명 |
| 출력 | Top N HSK 10자리 코드 + 신뢰도 점수 + 선정 사유 |
| 데이터 | 관세청 공개 데이터 직접 수집 |
| 우선순위 | 정확도 최우선 |
| 사용 형태 | 웹 UI + REST API |

## 2. 아키텍처

```
[사용자] → [React 웹 UI] → [FastAPI 백엔드]
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
             [1. 키워드 추출]  [2. 벡터 검색]  [3. LLM 리랭킹]
              (LLM: 기술→     (ChromaDB:      (LLM: 후보 중
               제품 키워드)    후보 30~50개)    Top N 선정)
                    │               │               │
                    └───────┬───────┘               │
                            ▼                       │
                     [HSK 코드 DB]                  │
                     (SQLite + ChromaDB)            │
                            ▲                       │
                            │                       ▼
                     [데이터 수집기]          [결과: Top N HSK
                     (관세청 크롤러)           + 신뢰도 점수]
```

### 기술 스택

| 컴포넌트 | 기술 |
|----------|------|
| 백엔드 | FastAPI |
| 프론트엔드 | React |
| 벡터 DB | ChromaDB (로컬 실행) |
| 관계형 DB | SQLite |
| LLM | OpenAI GPT-4o |
| 임베딩 | OpenAI text-embedding-3-small |

## 3. 데이터 수집 및 저장

### 데이터 소스

관세법령정보포털 (unipass.customs.go.kr)에서 HSK 10자리 품목분류표 수집. 약 12,000~15,000개 HSK 코드 예상.

### SQLite 스키마

```sql
CREATE TABLE hsk_codes (
    code TEXT PRIMARY KEY,       -- "8507.60-1000"
    name_kr TEXT NOT NULL,       -- "리튬이온 축전지"
    name_en TEXT,                -- "Lithium-ion accumulators"
    level INTEGER NOT NULL,      -- 류=1, 호=2, 소호=3, 통계부호=4, HSK=5
    parent_code TEXT,            -- "8507.60"
    description TEXT             -- 추가 설명/주해
);
```

모든 계층(류, 호, 소호, 통계부호, HSK)을 저장하여 트리 탐색 기능 지원. HSK 코드 형식은 `8507601000` (10자리 숫자, 구분자 없음)으로 통일. 화면 표시 시에만 `8507.60-1000` 형태로 포맷팅.

### ChromaDB

각 HSK 코드의 품목 설명(한글+영문)을 임베딩하여 저장. 메타데이터로 code, level, parent_code 포함.

### 데이터 갱신

HSK는 연 1~2회 개정. 수동 트리거 방식의 갱신 스크립트로 운영.

## 4. 핵심 파이프라인

### Step 1: 기술 → 제품 키워드 추출 (LLM)

- 입력: 자연어 기술 설명
- LLM에 "관련 제품, 물질, 부품, 장비를 한국어/영어로 추출" 프롬프트
- 직접 언급되지 않은 파생 제품도 추론
- 예상 소요: ~2초

### Step 2: 벡터 유사도 검색 (ChromaDB)

- Step 1의 키워드들을 임베딩하여 ChromaDB에서 유사도 검색
- 후보 HSK 코드 50개 추출 (설정 가능, 기본값 50)
- 키워드별 결과 합산/중복 제거, 유사도 임계값(기본 0.3) 이하 제외
- 예상 소요: ~0.5초

### Step 3: 리랭킹 및 최종 선정 (LLM)

- 원본 기술 설명 + 후보 코드 리스트를 LLM에 전달
- 관련도 순 Top N 선정 (top_n 최대값: 20) + 신뢰도 점수(0~1, LLM이 벡터 유사도와 의미적 관련성을 종합하여 산정) + 선정 사유
- 환각 방지: 후보 목록 안에서만 선택하도록 제약
- 예상 소요: ~3초

### 전체 파이프라인 예상 소요: ~5-6초

## 5. API 설계

```
POST /api/v1/classify
  Body: { "description": "...", "top_n": 5 }
  Response: {
    "results": [
      {
        "rank": 1,
        "hsk_code": "8507.60-1000",
        "name_kr": "리튬이온 축전지",
        "name_en": "Lithium-ion accumulators",
        "confidence": 0.92,
        "reason": "..."
      }, ...
    ],
    "keywords_extracted": ["양극재", "cathode material", ...],
    "processing_time_ms": 5200
  }

GET /api/v1/hsk/{code}
  — 특정 HSK 코드의 상세 정보 + 계층 구조 반환

GET /api/v1/hsk/search?q=배터리
  — HSK 코드 직접 텍스트 검색

POST /api/v1/data/refresh
  — 관세청 데이터 재수집 + 임베딩 재생성 트리거
```

### 에러 처리

- LLM API 호출 실패 시 재시도 (최대 2회) 후 에러 반환
- 빈 입력, 너무 짧은 입력(10자 미만) 등 기본 유효성 검사
- 임베딩 API 실패 시 에러 반환 (벡터 검색 불가)
- 파이프라인 전체 타임아웃: 30초

### 보안

- `/api/v1/data/refresh` 엔드포인트는 환경변수 `ADMIN_API_KEY` 헤더 인증 필요
- 사용자 입력은 LLM 프롬프트에 삽입 전 길이 제한 (최대 2000자)
- API 키는 `.env` 파일에서 관리, `.gitignore` 등록

## 6. 프론트엔드 UI

### 메인 화면 — 기술 입력 + 결과

- 텍스트 입력 영역 (여러 줄 가능)
- Top N 슬라이더 (기본값 5)
- "분류하기" 버튼
- 결과 테이블: 순위, HSK 코드, 품목명, 신뢰도(프로그레스바), 선정 사유
- 로딩 중 각 Step 진행 상태 표시 (SSE를 통해 Step 1/3, 2/3, 3/3 실시간 전달)

### HSK 코드 탐색 화면 (보조)

- HSK 코드 계층 트리 브라우저
- 텍스트 검색으로 코드 직접 조회

### UI 흐름

```
기술 설명 입력 → [분류하기] 클릭
    → 로딩 (Step 1 → Step 2 → Step 3)
    → 결과 테이블 표시
    → 각 행 클릭 시 HSK 코드 상세 정보 + 계층 구조 표시
```

## 7. 프로젝트 구조

```
11_hscode-connector/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   └── routes.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   └── pipeline.py
│   │   ├── services/
│   │   │   ├── keyword_extractor.py
│   │   │   ├── vector_search.py
│   │   │   └── reranker.py
│   │   ├── data/
│   │   │   ├── crawler.py
│   │   │   └── embedder.py
│   │   └── models/
│   │       └── schemas.py
│   ├── requirements.txt
│   └── .env
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── ClassifyPage.tsx
│   │   │   └── BrowsePage.tsx
│   │   └── components/
│   │       ├── ResultTable.tsx
│   │       └── HskTree.tsx
│   └── package.json
├── data/
├── docker-compose.yml
└── CLAUDE.md
```

## 8. 배포 및 환경 설정

### 환경 변수

```
OPENAI_API_KEY=          # OpenAI API 키 (LLM + 임베딩 공용)
ADMIN_API_KEY=           # 데이터 갱신 엔드포인트 인증 키
CHROMA_DB_PATH=./data/chromadb
SQLITE_DB_PATH=./data/hsk.db
```

### Docker Compose

- `backend` 컨테이너: FastAPI (호스트 포트는 PORT_REGISTRY.md에서 할당)
- `frontend` 컨테이너: React (Nginx 서빙, 호스트 포트는 PORT_REGISTRY.md에서 할당)
- 컨테이너 내부 포트: backend=8000, frontend=80 (표준값)
- `data/` 볼륨 마운트로 DB 영속성 확보

## 9. 테스트 전략

- **백엔드 단위 테스트**: 각 서비스(키워드 추출, 벡터 검색, 리랭킹) 개별 테스트
- **파이프라인 통합 테스트**: 실제 기술 설명 입력 → 결과 검증
- **API 테스트**: 엔드포인트 요청/응답 검증
- **정확도 평가**: 20~30개 R&D 기술 설명 샘플 + 기대 HSK 코드 쌍으로 Top-5 recall 측정
