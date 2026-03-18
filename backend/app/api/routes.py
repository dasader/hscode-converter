import os
import sqlite3
import logging
from fastapi import APIRouter, HTTPException, Header
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


def get_pipeline(settings: Settings) -> ClassificationPipeline:
    return ClassificationPipeline(
        keyword_extractor=KeywordExtractor(settings.openai_api_key),
        vector_search=VectorSearchService(settings.openai_api_key, settings.chroma_db_path),
        reranker=Reranker(settings.openai_api_key),
        vector_search_limit=settings.vector_search_limit,
        similarity_threshold=settings.similarity_threshold,
        pipeline_timeout=settings.pipeline_timeout,
    )


def ensure_data_dirs(settings: Settings) -> None:
    os.makedirs(os.path.dirname(settings.sqlite_db_path), exist_ok=True)
    os.makedirs(settings.chroma_db_path, exist_ok=True)


@router.post("/classify", response_model=ClassifyResponse)
async def classify(request: ClassifyRequest):
    settings = get_settings()
    pipeline = get_pipeline(settings)
    result = await pipeline.classify(request.description, request.top_n)
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


@router.get("/hsk/search", response_model=HskSearchResult)
async def search_hsk(q: str, limit: int = 20):
    settings = get_settings()
    conn = sqlite3.connect(settings.sqlite_db_path)
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT code, name_kr, name_en, level, parent_code, description FROM hsk_codes WHERE name_kr LIKE ? OR name_en LIKE ? OR code LIKE ? LIMIT ?",
        (f"%{q}%", f"%{q}%", f"%{q}%", limit),
    ).fetchall()
    conn.close()
    results = [HskCodeDetail(code=r[0], name_kr=r[1], name_en=r[2], level=r[3], parent_code=r[4], description=r[5]) for r in rows]
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
    children = [HskCodeDetail(code=c[0], name_kr=c[1], name_en=c[2], level=c[3], parent_code=c[4], description=c[5]) for c in children_rows]
    return HskCodeDetail(code=row[0], name_kr=row[1], name_en=row[2], level=row[3], parent_code=row[4], description=row[5], children=children)


@router.post("/data/refresh")
async def refresh_data(x_admin_key: str = Header(alias="X-Admin-Key")):
    settings = get_settings()
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=403, detail="인증 실패")
    ensure_data_dirs(settings)
    crawler = HskCrawler()
    records = await crawler.fetch_all()
    crawler.save_to_sqlite(records, settings.sqlite_db_path)
    embedder = HskEmbedder(settings.openai_api_key, settings.chroma_db_path)
    embedder.embed_from_sqlite(settings.sqlite_db_path)
    return {"status": "ok", "records_count": len(records)}
