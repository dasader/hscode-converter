import pytest
from app.models.schemas import ClassifyRequest, ClassifyResult, ClassifyResponse


def test_classify_request_defaults():
    req = ClassifyRequest(description="리튬이온 배터리 양극재 제조 기술")
    assert req.top_n == 5
    assert req.description == "리튬이온 배터리 양극재 제조 기술"


def test_classify_request_validates_top_n():
    with pytest.raises(ValueError):
        ClassifyRequest(description="test", top_n=25)


def test_classify_request_validates_short_input():
    with pytest.raises(ValueError):
        ClassifyRequest(description="짧은")


def test_classify_request_validates_long_input():
    with pytest.raises(ValueError):
        ClassifyRequest(description="가" * 2001)


def test_classify_result_fields():
    result = ClassifyResult(
        rank=1, hsk_code="8507601000", name_kr="리튬이온 축전지",
        name_en="Lithium-ion accumulators", confidence=0.92,
        reason="양극재는 리튬이온 축전지의 핵심 구성 요소",
    )
    assert result.hsk_code == "8507601000"
    assert result.confidence == 0.92


def test_classify_response_fields():
    resp = ClassifyResponse(results=[], keywords_extracted=["양극재"], processing_time_ms=5200)
    assert resp.processing_time_ms == 5200
