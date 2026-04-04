"""
리랭커 API 호출 시간 측정 테스트
실제 Gemini API를 호출하여 리랭킹 소요 시간을 측정합니다.
"""
import asyncio
import time
import os
import pytest
from dotenv import load_dotenv
from app.services.reranker import Reranker
from app.services.vector_search import SearchCandidate

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

# 실제 배치 처리와 유사한 후보 50개
MOCK_CANDIDATES = [
    SearchCandidate(code=f"850760{i:04d}", name=f"후보품목_{i}", distance=0.1 + i * 0.01)
    for i in range(50)
]

SAMPLE_DESCRIPTION = (
    "리튬이온 배터리 양극재 제조를 위한 니켈-코발트-망간(NCM) 전구체 합성 기술. "
    "공침법을 통해 균일한 입도분포의 전구체를 제조하고, 소성 공정을 통해 "
    "고용량 양극활물질을 생산하는 기술이다. 에너지밀도 향상을 위한 고니켈계 "
    "조성 최적화 및 표면코팅 기술을 포함한다."
)


@pytest.mark.asyncio
@pytest.mark.skipif(not GOOGLE_API_KEY, reason="GOOGLE_API_KEY 없음")
async def test_reranker_single_call_timing():
    """단일 리랭킹 호출 소요 시간 측정"""
    reranker = Reranker(api_key=GOOGLE_API_KEY, model=GEMINI_MODEL)

    start = time.monotonic()
    results = await reranker.rerank(SAMPLE_DESCRIPTION, MOCK_CANDIDATES[:50], top_n=5)
    elapsed = time.monotonic() - start

    print(f"\n[단일 호출] 후보 50개 → 소요 시간: {elapsed:.2f}s, 결과: {len(results)}개")
    assert elapsed < 120, f"단일 리랭킹이 120초 초과: {elapsed:.2f}s"


@pytest.mark.asyncio
@pytest.mark.skipif(not GOOGLE_API_KEY, reason="GOOGLE_API_KEY 없음")
async def test_reranker_concurrent_timing():
    """동시 리랭킹 호출 소요 시간 측정 (5개 동시)"""
    reranker = Reranker(api_key=GOOGLE_API_KEY, model=GEMINI_MODEL)

    async def one_call(idx: int):
        start = time.monotonic()
        results = await reranker.rerank(SAMPLE_DESCRIPTION, MOCK_CANDIDATES[:50], top_n=5)
        elapsed = time.monotonic() - start
        print(f"  [동시호출 #{idx}] 소요: {elapsed:.2f}s, 결과: {len(results)}개")
        return elapsed

    print("\n[5개 동시 호출 시작]")
    overall_start = time.monotonic()
    times = await asyncio.gather(*[one_call(i) for i in range(5)])
    overall_elapsed = time.monotonic() - overall_start

    print(f"[5개 동시] 전체: {overall_elapsed:.2f}s | 개별 min={min(times):.2f}s max={max(times):.2f}s avg={sum(times)/len(times):.2f}s")


@pytest.mark.asyncio
@pytest.mark.skipif(not GOOGLE_API_KEY, reason="GOOGLE_API_KEY 없음")
async def test_reranker_candidate_count_impact():
    """후보 수에 따른 소요 시간 비교 (10 / 20 / 50개)"""
    reranker = Reranker(api_key=GOOGLE_API_KEY, model=GEMINI_MODEL)

    for count in [10, 20, 50]:
        start = time.monotonic()
        await reranker.rerank(SAMPLE_DESCRIPTION, MOCK_CANDIDATES[:count], top_n=5)
        elapsed = time.monotonic() - start
        print(f"  [후보 {count:2d}개] 소요: {elapsed:.2f}s")
