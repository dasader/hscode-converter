from dataclasses import dataclass
import httpx
from bs4 import BeautifulSoup
import sqlite3
import logging

logger = logging.getLogger(__name__)


@dataclass
class HskRecord:
    code: str
    name_kr: str
    name_en: str
    level: int
    parent_code: str | None
    description: str


class HskCrawler:
    BASE_URL = "https://unipass.customs.go.kr"

    @staticmethod
    def format_code(code: str) -> str:
        code = code.strip()
        if len(code) <= 2:
            return code
        if len(code) == 4:
            return f"{code[:2]}.{code[2:]}"
        if len(code) == 6:
            return f"{code[:4]}.{code[4:]}"
        if len(code) == 8:
            return f"{code[:4]}.{code[4:6]}-{code[6:]}"
        if len(code) == 10:
            return f"{code[:4]}.{code[4:6]}-{code[6:]}"
        return code

    @staticmethod
    def determine_level(code: str) -> int:
        length_to_level = {2: 1, 4: 2, 6: 3, 8: 4, 10: 5}
        return length_to_level.get(len(code), 0)

    @staticmethod
    def determine_parent(code: str) -> str | None:
        parent_lengths = {10: 8, 8: 6, 6: 4, 4: 2}
        parent_len = parent_lengths.get(len(code))
        if parent_len is None:
            return None
        return code[:parent_len]

    async def fetch_all(self) -> list[HskRecord]:
        records: list[HskRecord] = []
        async with httpx.AsyncClient(timeout=60) as client:
            logger.info("관세청 HSK 데이터 수집 시작")
            for chapter in range(1, 98):
                chapter_code = f"{chapter:02d}"
                try:
                    chapter_records = await self._fetch_chapter(client, chapter_code)
                    records.extend(chapter_records)
                    logger.info(f"류 {chapter_code}: {len(chapter_records)}건 수집")
                except Exception as e:
                    logger.error(f"류 {chapter_code} 수집 실패: {e}")
        logger.info(f"총 {len(records)}건 수집 완료")
        return records

    async def _fetch_chapter(self, client: httpx.AsyncClient, chapter: str) -> list[HskRecord]:
        # TODO: 실제 관세청 API/페이지 구조에 맞게 구현
        return []

    def save_to_sqlite(self, records: list[HskRecord], db_path: str) -> None:
        import os
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hsk_codes (
                code TEXT PRIMARY KEY,
                name_kr TEXT NOT NULL,
                name_en TEXT,
                level INTEGER NOT NULL,
                parent_code TEXT,
                description TEXT
            )
        """)
        cursor.execute("DELETE FROM hsk_codes")
        cursor.executemany(
            "INSERT INTO hsk_codes (code, name_kr, name_en, level, parent_code, description) VALUES (?, ?, ?, ?, ?, ?)",
            [(r.code, r.name_kr, r.name_en, r.level, r.parent_code, r.description) for r in records],
        )
        conn.commit()
        conn.close()
        logger.info(f"SQLite 저장 완료: {len(records)}건 → {db_path}")
