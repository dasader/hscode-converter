import os
import tempfile
import sqlite3
import pytest
from app.data.crawler import HskCrawler, HskRecord


def test_hsk_record_creation():
    record = HskRecord(code="8507601000", name_kr="리튬이온 축전지", name_en="Lithium-ion accumulators", level=5, parent_code="850760", description="")
    assert record.code == "8507601000"
    assert record.level == 5


def test_format_hsk_code():
    assert HskCrawler.format_code("8507601000") == "8507.60-1000"
    assert HskCrawler.format_code("85") == "85"
    assert HskCrawler.format_code("8507") == "85.07"
    assert HskCrawler.format_code("850760") == "8507.60"


def test_determine_level():
    assert HskCrawler.determine_level("85") == 1
    assert HskCrawler.determine_level("8507") == 2
    assert HskCrawler.determine_level("850760") == 3
    assert HskCrawler.determine_level("85076010") == 4
    assert HskCrawler.determine_level("8507601000") == 5


def test_determine_parent():
    assert HskCrawler.determine_parent("8507601000") == "85076010"
    assert HskCrawler.determine_parent("85076010") == "850760"
    assert HskCrawler.determine_parent("850760") == "8507"
    assert HskCrawler.determine_parent("8507") == "85"
    assert HskCrawler.determine_parent("85") is None


def test_save_to_sqlite_and_data_sources():
    records = [
        HskRecord(code="8507601000", name_kr="리튬이온 축전지", name_en="Lithium-ion accumulators", level=5, parent_code="85076010", description=""),
        HskRecord(code="85", name_kr="[85]", name_en="", level=1, parent_code=None, description=""),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        crawler = HskCrawler()
        crawler.save_to_sqlite(records, db_path, source_file="관세청_HS부호_20260101.xlsx")

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        count = cursor.execute("SELECT COUNT(*) FROM hsk_codes").fetchone()[0]
        assert count == 2

        sources = cursor.execute("SELECT file_name, record_count FROM data_sources").fetchall()
        assert len(sources) == 1
        assert sources[0][0] == "관세청_HS부호_20260101.xlsx"
        assert sources[0][1] == 2
        conn.close()


def test_load_from_excel():
    """실제 관세청 엑셀 파일이 있으면 로드 테스트"""
    excel_path = "C:/Users/ilhwa/Downloads/관세청_HS부호_20260101.xlsx"
    if not os.path.exists(excel_path):
        pytest.skip("관세청 엑셀 파일 없음")
    crawler = HskCrawler()
    records = crawler.load_from_excel(excel_path)
    assert len(records) > 10000
    # 10자리 HSK 코드가 있는지 확인
    hsk_records = [r for r in records if r.level == 5]
    assert len(hsk_records) > 10000
    # 상위 코드도 생성되었는지 확인
    parent_records = [r for r in records if r.level < 5]
    assert len(parent_records) > 0
