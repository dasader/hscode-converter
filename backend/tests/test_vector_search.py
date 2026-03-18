import pytest
from app.services.vector_search import VectorSearchService, SearchCandidate


def test_search_candidate_creation():
    c = SearchCandidate(code="8507601000", name="리튬이온 축전지", distance=0.15)
    assert c.code == "8507601000"
    assert c.distance == 0.15


def test_deduplicate_candidates():
    candidates = [
        SearchCandidate(code="8507601000", name="리튬이온 축전지", distance=0.1),
        SearchCandidate(code="8507601000", name="리튬이온 축전지", distance=0.2),
        SearchCandidate(code="2827399000", name="니켈 코발트 산화물", distance=0.3),
    ]
    deduped = VectorSearchService.deduplicate(candidates)
    assert len(deduped) == 2
    assert deduped[0].distance == 0.1


def test_filter_by_threshold():
    candidates = [
        SearchCandidate(code="A", name="a", distance=0.1),
        SearchCandidate(code="B", name="b", distance=0.5),
        SearchCandidate(code="C", name="c", distance=0.8),
    ]
    filtered = VectorSearchService.filter_by_threshold(candidates, threshold=0.3)
    assert len(filtered) == 1
    assert filtered[0].code == "A"
