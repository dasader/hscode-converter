import os
import shutil
import sqlite3
import logging
from fastapi import APIRouter, HTTPException, Header, UploadFile, File
from app.core.config import Settings
from app.core.pipeline import ClassificationPipeline
from app.services.keyword_extractor import KeywordExtractor
from app.services.vector_search import VectorSearchService
from app.services.reranker import Reranker
from app.data.crawler import HskCrawler
from app.data.embedder import HskEmbedder
from app.models.schemas import ClassifyRequest, ClassifyResult, ClassifyResponse, HskCodeDetail, HskSearchResult

logger = logging.getLogger(__name__)
router = APIRouter()


def get_settings() -> Settings:
    return Settings()


_pipeline_instance: ClassificationPipeline | None = None


def get_pipeline(settings: Settings | None = None) -> ClassificationPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        if settings is None:
            settings = get_settings()
        _pipeline_instance = ClassificationPipeline(
            keyword_extractor=KeywordExtractor(settings.openai_api_key),
            vector_search=VectorSearchService(settings.openai_api_key, settings.chroma_db_path),
            reranker=Reranker(settings.openai_api_key),
            vector_search_limit=settings.vector_search_limit,
            similarity_threshold=settings.similarity_threshold,
            pipeline_timeout=settings.pipeline_timeout,
        )
    return _pipeline_instance


def ensure_data_dirs(settings: Settings) -> None:
    os.makedirs(os.path.dirname(settings.sqlite_db_path), exist_ok=True)
    os.makedirs(settings.chroma_db_path, exist_ok=True)


@router.post("/classify", response_model=ClassifyResponse)
async def classify(request: ClassifyRequest):
    settings = get_settings()
    pipeline = get_pipeline(settings)
    result = await pipeline.classify(request.description, request.top_n, request.model)
    conn = sqlite3.connect(settings.sqlite_db_path)
    cursor = conn.cursor()
    classify_results = []
    for i, item in enumerate(result.results, 1):
        row = cursor.execute("SELECT name_kr, name_en FROM hsk_codes WHERE code = ?", (item["code"],)).fetchone()
        classify_results.append(ClassifyResult(
            rank=i, hsk_code=HskCrawler.format_code(item["code"]),
            name_kr=row[0] if row else item.get("code", ""),
            name_en=row[1] if row else None,
            confidence=item.get("confidence", 0.0), reason=item.get("reason", ""),
        ))
    conn.close()
    return ClassifyResponse(results=classify_results, keywords_extracted=result.keywords, processing_time_ms=result.processing_time_ms)


def _make_detail(r) -> HskCodeDetail:
    return HskCodeDetail(
        code=r[0], formatted_code=HskCrawler.format_code(r[0]),
        name_kr=r[1], name_en=r[2], level=r[3], parent_code=r[4], description=r[5],
    )


@router.get("/hsk/search", response_model=HskSearchResult)
async def search_hsk(q: str, limit: int = 20):
    settings = get_settings()
    # 포맷된 코드(8507.60-1000)로 검색 시 raw 코드로 변환
    q_raw = q.replace(".", "").replace("-", "")
    conn = sqlite3.connect(settings.sqlite_db_path)
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT code, name_kr, name_en, level, parent_code, description FROM hsk_codes WHERE name_kr LIKE ? OR name_en LIKE ? OR code LIKE ? OR code LIKE ? LIMIT ?",
        (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q_raw}%", limit),
    ).fetchall()
    conn.close()
    results = [_make_detail(r) for r in rows]
    return HskSearchResult(results=results, total=len(results))


@router.get("/hsk/{code}", response_model=HskCodeDetail)
async def get_hsk_code(code: str):
    settings = get_settings()
    conn = sqlite3.connect(settings.sqlite_db_path)
    cursor = conn.cursor()
    row = cursor.execute("SELECT code, name_kr, name_en, level, parent_code, description FROM hsk_codes WHERE code = ?", (code,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="HSK 코드를 찾을 수 없습니다")
    children_rows = cursor.execute("SELECT code, name_kr, name_en, level, parent_code, description FROM hsk_codes WHERE parent_code = ?", (code,)).fetchall()
    conn.close()
    children = [_make_detail(c) for c in children_rows]
    detail = _make_detail(row)
    detail.children = children
    return detail


@router.post("/data/refresh")
async def refresh_data(
    file: UploadFile = File(..., description="관세청 HS부호 엑셀 파일 (.xlsx)"),
    x_admin_key: str = Header(alias="X-Admin-Key"),
):
    """관세청 HS부호 엑셀 파일을 업로드하여 데이터를 갱신합니다."""
    settings = get_settings()
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="인증 실패")
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail=".xlsx 파일만 지원합니다")

    ensure_data_dirs(settings)

    # 업로드 파일을 data/ 디렉터리에 저장
    upload_path = os.path.join(os.path.dirname(settings.sqlite_db_path), file.filename)
    with open(upload_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    crawler = HskCrawler()
    records = crawler.load_from_excel(upload_path)
    crawler.save_to_sqlite(records, settings.sqlite_db_path, source_file=upload_path)

    embedder = HskEmbedder(settings.openai_api_key, settings.chroma_db_path)
    embedder.embed_from_sqlite(settings.sqlite_db_path)

    return {"status": "ok", "records_count": len(records), "source_file": file.filename}


@router.get("/data/sources")
async def get_data_sources():
    """현재 로드된 데이터 소스 이력을 조회합니다."""
    settings = get_settings()
    if not os.path.exists(settings.sqlite_db_path):
        return {"sources": []}
    conn = sqlite3.connect(settings.sqlite_db_path)
    cursor = conn.cursor()
    try:
        rows = cursor.execute("SELECT file_name, loaded_at, record_count FROM data_sources ORDER BY id DESC").fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return {"sources": [{"file_name": r[0], "loaded_at": r[1], "record_count": r[2]} for r in rows]}
