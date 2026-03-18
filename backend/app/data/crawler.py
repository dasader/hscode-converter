from dataclasses import dataclass
import os
import sqlite3
import logging
from datetime import datetime

import openpyxl

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
    """관세청 HS부호 엑셀 파일에서 HSK 코드를 로드하여 SQLite에 저장"""

    @staticmethod
    def format_code(code: str) -> str:
        """10자리 숫자 코드를 표시 형식으로 변환"""
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
        """코드 길이로 계층 수준 결정"""
        length_to_level = {2: 1, 4: 2, 6: 3, 8: 4, 10: 5}
        return length_to_level.get(len(code), 0)

    @staticmethod
    def determine_parent(code: str) -> str | None:
        """부모 코드 결정"""
        parent_lengths = {10: 8, 8: 6, 6: 4, 4: 2}
        parent_len = parent_lengths.get(len(code))
        if parent_len is None:
            return None
        return code[:parent_len]

    def load_from_excel(self, excel_path: str) -> list[HskRecord]:
        """관세청 HS부호 엑셀 파일에서 HSK 코드를 로드.

        엑셀 컬럼 구조 (관세청_HS부호_YYYYMMDD.xlsx):
          열0: HS부호 (10자리)
          열3: 한글품목명
          열4: 영문품목명
          열5: HS부호내용 (설명, 대부분 None)
        """
        logger.info(f"엑셀 파일 로드 시작: {excel_path}")
        wb = openpyxl.load_workbook(excel_path, read_only=True)
        ws = wb.active

        records: list[HskRecord] = []
        parent_codes_seen: set[str] = set()

        # 1차: 엑셀의 10자리 HSK 코드를 모두 읽기
        for row in ws.iter_rows(min_row=2, values_only=True):
            code = str(row[0]).strip() if row[0] else ""
            if not code or len(code) != 10 or not code.isdigit():
                continue

            name_kr = str(row[3]).strip() if row[3] else ""
            name_en = str(row[4]).strip() if row[4] else ""
            description = str(row[5]).strip() if row[5] else ""

            record = HskRecord(
                code=code,
                name_kr=name_kr,
                name_en=name_en,
                level=5,  # HSK 10자리
                parent_code=code[:8],
                description=description,
            )
            records.append(record)

            # 상위 계층 코드 수집
            for length in [2, 4, 6, 8]:
                parent_codes_seen.add(code[:length])

        wb.close()

        # 2차: 상위 계층 코드 생성 (류/호/소호/통계부호)
        # 상위 코드의 품목명은 하위 코드에서 유추할 수 없으므로 코드만 등록
        parent_records = []
        existing_codes = {r.code for r in records}
        for pcode in sorted(parent_codes_seen):
            if pcode not in existing_codes:
                parent_records.append(HskRecord(
                    code=pcode,
                    name_kr=f"[{self.format_code(pcode)}]",
                    name_en="",
                    level=self.determine_level(pcode),
                    parent_code=self.determine_parent(pcode),
                    description="",
                ))

        all_records = parent_records + records
        logger.info(f"엑셀 로드 완료: HSK {len(records)}건 + 상위코드 {len(parent_records)}건 = 총 {len(all_records)}건")
        return all_records

    def save_to_sqlite(self, records: list[HskRecord], db_path: str, source_file: str = "") -> None:
        """수집한 레코드를 SQLite에 저장하고 데이터 소스 이력 기록"""
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                loaded_at TEXT NOT NULL,
                record_count INTEGER NOT NULL
            )
        """)

        cursor.execute("DELETE FROM hsk_codes")
        cursor.executemany(
            "INSERT INTO hsk_codes (code, name_kr, name_en, level, parent_code, description) VALUES (?, ?, ?, ?, ?, ?)",
            [(r.code, r.name_kr, r.name_en, r.level, r.parent_code, r.description) for r in records],
        )

        if source_file:
            cursor.execute(
                "INSERT INTO data_sources (file_name, loaded_at, record_count) VALUES (?, ?, ?)",
                (os.path.basename(source_file), datetime.now().isoformat(), len(records)),
            )

        conn.commit()
        conn.close()
        logger.info(f"SQLite 저장 완료: {len(records)}건 → {db_path}")
