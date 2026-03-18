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
