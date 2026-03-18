import asyncio
import time
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable
from app.services.keyword_extractor import KeywordExtractor
from app.services.vector_search import VectorSearchService
from app.services.reranker import Reranker

logger = logging.getLogger(__name__)


class PipelineStep(Enum):
    KEYWORD_EXTRACTION = "keyword_extraction"
    VECTOR_SEARCH = "vector_search"
    RERANKING = "reranking"


@dataclass
class PipelineResult:
    keywords: list[str]
    results: list[dict]
    processing_time_ms: int = 0


class ClassificationPipeline:
    def __init__(self, keyword_extractor: KeywordExtractor, vector_search: VectorSearchService, reranker: Reranker,
                 vector_search_limit: int = 50, similarity_threshold: float = 0.3, pipeline_timeout: int = 30):
        self.keyword_extractor = keyword_extractor
        self.vector_search = vector_search
        self.reranker = reranker
        self.vector_search_limit = vector_search_limit
        self.similarity_threshold = similarity_threshold
        self.pipeline_timeout = pipeline_timeout

    async def classify(self, description: str, top_n: int = 5, model: str = "chatgpt-5.4-mini", on_step: Callable[[PipelineStep], None] | None = None) -> PipelineResult:
        return await asyncio.wait_for(self._classify_impl(description, top_n, model, on_step), timeout=self.pipeline_timeout)

    async def _classify_impl(self, description: str, top_n: int = 5, model: str = "chatgpt-5.4-mini", on_step: Callable[[PipelineStep], None] | None = None) -> PipelineResult:
        start = time.time()
        if on_step:
            on_step(PipelineStep.KEYWORD_EXTRACTION)
        keywords = await self.keyword_extractor.extract(description, model=model)
        if on_step:
            on_step(PipelineStep.VECTOR_SEARCH)
        candidates = self.vector_search.search(keywords, limit=self.vector_search_limit, threshold=self.similarity_threshold)
        if on_step:
            on_step(PipelineStep.RERANKING)
        results = await self.reranker.rerank(description, candidates, top_n, model=model)
        elapsed_ms = int((time.time() - start) * 1000)
        logger.info(f"파이프라인 완료: {elapsed_ms}ms")
        return PipelineResult(keywords=keywords, results=results, processing_time_ms=elapsed_ms)
