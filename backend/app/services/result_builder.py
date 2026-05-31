import sqlite3

from app.data.crawler import HskCrawler


def effective_top_n(top_n: int, confidence_threshold: float | None, max_top_n_with_threshold: int) -> int:
    """confidence_threshold가 지정되면 임계값 필터를 위해 더 많은 후보를 가져온다."""
    return max_top_n_with_threshold if confidence_threshold is not None else top_n


def filter_by_confidence(results: list[dict], threshold: float | None) -> list[dict]:
    """신뢰도 임계값 이상인 결과만 남긴다. threshold가 None이면 그대로 반환."""
    if threshold is None:
        return results
    return [r for r in results if r.get("confidence", 0) >= threshold]


def enrich_results(results: list[dict], db_path: str) -> list[dict]:
    """파이프라인 결과(code/confidence/reason)에 SQLite의 품목명을 붙여 표시용 dict로 변환.

    코드 전체를 단일 `WHERE code IN (...)` 쿼리로 조회하여 N+1을 피한다.
    DB 조회 실패 시 품목명은 코드로 폴백한다.
    """
    codes = [r.get("code", "") for r in results]
    name_map: dict[str, tuple] = {}
    if codes:
        try:
            conn = sqlite3.connect(db_path)
            try:
                placeholders = ",".join("?" * len(codes))
                rows = conn.execute(
                    f"SELECT code, name_kr, name_en FROM hsk_codes WHERE code IN ({placeholders})",
                    codes,
                ).fetchall()
                name_map = {row[0]: (row[1], row[2]) for row in rows}
            finally:
                conn.close()
        except Exception:
            name_map = {}

    enriched = []
    for i, r in enumerate(results, 1):
        code = r.get("code", "")
        name_kr, name_en = name_map.get(code, (code, None))
        enriched.append({
            "rank": i,
            "hsk_code": HskCrawler.format_code(code),
            "name_kr": name_kr,
            "name_en": name_en,
            "confidence": r.get("confidence", 0.0),
            "reason": r.get("reason", ""),
        })
    return enriched
