import asyncio
from dataclasses import dataclass
import logging
from openai import AsyncOpenAI
import chromadb

logger = logging.getLogger(__name__)


@dataclass
class SearchCandidate:
    code: str
    name: str
    distance: float


class VectorSearchService:
    EMBEDDING_MODEL = "text-embedding-3-small"

    def __init__(self, openai_api_key: str, chroma_db_path: str):
        self.openai_client = AsyncOpenAI(api_key=openai_api_key)
        self.chroma_client = chromadb.PersistentClient(path=chroma_db_path)

    @staticmethod
    def deduplicate(candidates: list[SearchCandidate]) -> list[SearchCandidate]:
        best: dict[str, SearchCandidate] = {}
        for c in candidates:
            if c.code not in best or c.distance < best[c.code].distance:
                best[c.code] = c
        return sorted(best.values(), key=lambda x: x.distance)

    @staticmethod
    def filter_by_threshold(candidates: list[SearchCandidate], threshold: float) -> list[SearchCandidate]:
        return [c for c in candidates if c.distance <= threshold]

    async def search(self, keywords: list[str], limit: int = 50, threshold: float = 0.3,
                     rate_limiter=None) -> list[SearchCandidate]:
        collection = await asyncio.to_thread(self.chroma_client.get_collection, "hsk_codes")
        all_candidates: list[SearchCandidate] = []
        for keyword in keywords:
            if rate_limiter:
                await rate_limiter.acquire(rpm=1, tpm=10)
            embedding = await self._get_embedding(keyword)
            results = await asyncio.to_thread(
                collection.query, query_embeddings=[embedding],
                n_results=min(limit, 50), include=["documents", "distances", "metadatas"],
            )
            if results["ids"] and results["ids"][0]:
                for code, doc, dist in zip(results["ids"][0], results["documents"][0], results["distances"][0]):
                    all_candidates.append(SearchCandidate(code=code, name=doc, distance=dist))
        deduped = self.deduplicate(all_candidates)
        filtered = self.filter_by_threshold(deduped, threshold)
        result = filtered[:limit]
        logger.info(f"벡터 검색 완료: {len(keywords)}개 키워드 → {len(result)}개 후보")
        return result

    async def _get_embedding(self, text: str) -> list[float]:
        response = await self.openai_client.embeddings.create(model=self.EMBEDDING_MODEL, input=[text])
        return response.data[0].embedding
