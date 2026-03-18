import glob
import os
import sqlite3
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router, ensure_data_dirs
from app.core.config import Settings

logger = logging.getLogger(__name__)


def _db_has_data(db_path: str) -> bool:
    """SQLite DB에 hsk_codes 테이블이 있고 데이터가 있는지 확인"""
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM hsk_codes").fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


def _auto_load_excel(settings: Settings) -> None:
    """data/ 폴더에 엑셀 파일이 있고 DB가 비어있으면 자동 로드"""
    if _db_has_data(settings.sqlite_db_path):
        logger.info("HSK 데이터가 이미 존재합니다. 자동 로드를 건너뜁니다.")
        return

    # data/ 폴더에서 .xlsx 파일 찾기 (가장 최신 파일 사용)
    pattern = os.path.join(settings.excel_dir, "*.xlsx")
    xlsx_files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if not xlsx_files:
        logger.warning(f"자동 로드할 엑셀 파일이 없습니다. {settings.excel_dir}/ 폴더에 관세청 HS부호 엑셀 파일을 넣어주세요.")
        return

    excel_path = xlsx_files[0]
    logger.info(f"HSK 데이터 자동 로드 시작: {excel_path}")

    from app.data.crawler import HskCrawler
    from app.data.embedder import HskEmbedder

    crawler = HskCrawler()
    records = crawler.load_from_excel(excel_path)
    crawler.save_to_sqlite(records, settings.sqlite_db_path, source_file=excel_path)
    logger.info(f"SQLite 저장 완료: {len(records)}건")

    logger.info("임베딩 생성 시작 (최초 실행 시 수 분 소요)...")
    embedder = HskEmbedder(settings.openai_api_key, settings.chroma_db_path)
    embedder.embed_from_sqlite(settings.sqlite_db_path)
    logger.info("임베딩 생성 완료. 서비스 준비됨.")


def create_app() -> FastAPI:
    app = FastAPI(title="HSCode Connector", version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(router, prefix="/api/v1")

    @app.on_event("startup")
    async def startup():
        try:
            settings = Settings()
            ensure_data_dirs(settings)
            _auto_load_excel(settings)
        except Exception as e:
            logger.error(f"시작 시 자동 로드 실패: {e}")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
