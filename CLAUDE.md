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
