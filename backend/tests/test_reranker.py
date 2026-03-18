import pytest
import json
from app.services.reranker import Reranker


def test_build_candidates_text():
    from app.services.vector_search import SearchCandidate
    candidates = [
        SearchCandidate(code="8507601000", name="리튬이온 축전지", distance=0.1),
        SearchCandidate(code="2827399000", name="니켈 코발트 산화물", distance=0.2),
    ]
    text = Reranker.build_candidates_text(candidates)
    assert "8507601000" in text
    assert "리튬이온 축전지" in text
    assert "2827399000" in text


def test_parse_rerank_response_valid():
    raw = json.dumps([
        {"code": "8507601000", "confidence": 0.92, "reason": "직접 관련"},
        {"code": "2827399000", "confidence": 0.85, "reason": "원료 관련"},
    ])
    results = Reranker.parse_response(raw)
    assert len(results) == 2
    assert results[0]["code"] == "8507601000"
    assert results[0]["confidence"] == 0.92


def test_parse_rerank_response_extracts_json_from_markdown():
    raw = '```json\n[{"code": "8507601000", "confidence": 0.9, "reason": "관련"}]\n```'
    results = Reranker.parse_response(raw)
    assert len(results) == 1
