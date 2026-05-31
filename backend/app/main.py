import glob
import os
import sqlite3
import threading
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router, ensure_data_dirs, get_pipeline
from app.api.batch_routes import router as batch_router, init_batch
from app.core.config import Settings
from app.core import state
from app.data.batch_db import BatchDB
from app.services.batch_service import BatchService
from app.services.batch_worker import BatchWorker
from app.services.rate_limiter import TokenBucketLimiter

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# 노이즈 로거 억제
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)

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


def _chroma_has_data(chroma_path: str, sqlite_db_path: str | None = None) -> bool:
    try:
        import chromadb
        client = chromadb.PersistentClient(path=chroma_path)
        collection = client.get_collection("hsk_codes")
        chroma_count = collection.count()
        if chroma_count == 0:
            return False
        if sqlite_db_path and os.path.exists(sqlite_db_path):
            conn = sqlite3.connect(sqlite_db_path)
            sqlite_count = conn.execute("SELECT COUNT(*) FROM hsk_codes WHERE level=5").fetchone()[0]
            conn.close()
            if sqlite_count > 0 and chroma_count < sqlite_count * 0.9:
                logger.warning(f"ChromaDB 불완전: {chroma_count}/{sqlite_count}건 — 재임베딩 필요")
                return False
        # HNSW 인덱스에 실제 벡터가 있는지 확인 (metadata만 있고 벡터가 없는 경우 대비)
        peek = collection.peek(limit=1)
        embeddings = peek.get("embeddings")
        if not embeddings or len(embeddings) == 0:
            logger.warning("ChromaDB HNSW 벡터 인덱스가 비어 있음 — 재임베딩 필요")
            return False
        return True
    except Exception:
        return False


def _auto_load_sync(settings: Settings) -> None:
    try:
        db_ok = _db_has_data(settings.sqlite_db_path)
        chroma_ok = _chroma_has_data(settings.chroma_db_path, settings.sqlite_db_path)

        if db_ok and chroma_ok:
            logger.info("HSK 데이터와 임베딩이 이미 존재합니다.")
            state.loading_status = {"state": "ready", "message": "데이터 준비 완료"}
            state.data_ready.set()
            return

        pattern = os.path.join(settings.excel_dir, "*.xlsx")
        xlsx_files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if not xlsx_files:
            logger.warning(f"자동 로드할 엑셀 파일이 없습니다. {settings.excel_dir}/ 폴더에 관세청 HS부호 엑셀 파일을 넣어주세요.")
            state.loading_status = {"state": "no_data", "message": "엑셀 파일 없음. data/ 폴더에 파일을 넣어주세요."}
            return

        excel_path = xlsx_files[0]

        if not db_ok:
            state.loading_status = {"state": "loading", "message": f"엑셀 로드 중: {os.path.basename(excel_path)}"}
            logger.info(f"HSK 데이터 로드 시작: {excel_path}")
            from app.data.crawler import HskCrawler
            crawler = HskCrawler()
            records = crawler.load_from_excel(excel_path)
            crawler.save_to_sqlite(records, settings.sqlite_db_path, source_file=excel_path)
            logger.info(f"SQLite 저장 완료: {len(records)}건")

        if not chroma_ok:
            state.loading_status = {"state": "embedding", "message": "임베딩 생성 중 (수 분 소요)..."}
            logger.info("임베딩 생성 시작...")
            from app.data.embedder import HskEmbedder
            embedder = HskEmbedder(settings.google_api_key, settings.chroma_db_path, settings.gemini_embedding_model)
            embedder.embed_from_sqlite(settings.sqlite_db_path)
            logger.info("임베딩 생성 완료.")

        state.loading_status = {"state": "ready", "message": "데이터 준비 완료"}
        state.data_ready.set()

    except Exception as e:
        logger.error(f"자동 로드 실패: {e}", exc_info=True)
        state.loading_status = {"state": "error", "message": str(e)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _batch_worker
    try:
        settings = Settings()
        ensure_data_dirs(settings)

        thread = threading.Thread(target=_auto_load_sync, args=(settings,), daemon=True)
        thread.start()

        batch_db_path = os.path.join(os.path.dirname(settings.sqlite_db_path), "batch.db")
        batch_db = BatchDB(batch_db_path)
        batch_service = BatchService(batch_db)
        rate_limiter = TokenBucketLimiter(rpm=500, tpm=500000)
        pipeline = get_pipeline(settings)
        _batch_worker = BatchWorker(
            db=batch_db, pipeline=pipeline, settings=settings,
            num_workers=5, rate_limiter=rate_limiter,
        )
        init_batch(batch_db, batch_service, _batch_worker)

        await _batch_worker.start()

        recovered = batch_db.recover_incomplete_items()
        if recovered:
            logger.info(f"미완료 배치 작업 {len(recovered)}건 복원")
            await _batch_worker.enqueue_items(recovered)

    except Exception as e:
        logger.error(f"시작 실패: {e}", exc_info=True)

    yield

    if _batch_worker:
        await _batch_worker.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="HSCode Connector", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(router, prefix="/api/v1")
    app.include_router(batch_router, prefix="/api/v1")

    @app.get("/health")
    async def health():
        return {"status": "ok", "data": state.loading_status}

    @app.get("/api/v1/data/status")
    async def data_status():
        return state.loading_status

    return app


app = create_app()
