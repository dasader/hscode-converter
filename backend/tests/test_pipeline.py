import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.pipeline import ClassificationPipeline, PipelineStep


def test_pipeline_step_enum():
    assert PipelineStep.KEYWORD_EXTRACTION.value == "keyword_extraction"
    assert PipelineStep.VECTOR_SEARCH.value == "vector_search"
    assert PipelineStep.RERANKING.value == "reranking"


@pytest.mark.asyncio
async def test_pipeline_runs_all_steps():
    mock_extractor = AsyncMock()
    mock_extractor.extract.return_value = ["양극재", "cathode material"]
    mock_search = MagicMock()
    from app.services.vector_search import SearchCandidate
    mock_search.search = AsyncMock(return_value=[SearchCandidate(code="8507601000", name="리튬이온 축전지", distance=0.1)])
    mock_reranker = AsyncMock()
    mock_reranker.rerank.return_value = [{"code": "8507601000", "confidence": 0.92, "reason": "관련"}]
    pipeline = ClassificationPipeline(keyword_extractor=mock_extractor, vector_search=mock_search, reranker=mock_reranker)
    result = await pipeline.classify("리튬이온 배터리 양극재 제조 기술", top_n=5)
    assert result.keywords == ["양극재", "cathode material"]
    assert len(result.results) == 1
    assert result.results[0]["code"] == "8507601000"
    mock_extractor.extract.assert_called_once()
    mock_search.search.assert_called_once()
    mock_reranker.rerank.assert_called_once()
