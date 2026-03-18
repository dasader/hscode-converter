import asyncio
import time
import pytest
from app.services.rate_limiter import TokenBucket, TokenBucketLimiter


@pytest.mark.asyncio
async def test_token_bucket_consume_success():
    bucket = TokenBucket(capacity=10, refill_rate=10)
    assert await bucket.consume(5) is True


@pytest.mark.asyncio
async def test_token_bucket_consume_insufficient():
    bucket = TokenBucket(capacity=2, refill_rate=1)
    await bucket.consume(2)
    assert await bucket.consume(1) is False


@pytest.mark.asyncio
async def test_token_bucket_refill():
    bucket = TokenBucket(capacity=10, refill_rate=100)
    await bucket.consume(10)
    await asyncio.sleep(0.15)
    assert await bucket.consume(10) is True


@pytest.mark.asyncio
async def test_token_bucket_return_tokens():
    bucket = TokenBucket(capacity=10, refill_rate=0)
    await bucket.consume(8)
    await bucket.return_tokens(5)
    assert await bucket.consume(7) is True


@pytest.mark.asyncio
async def test_limiter_acquire_waits():
    limiter = TokenBucketLimiter(rpm=5, tpm=100000, rpm_safety=1.0, tpm_safety=1.0)
    for _ in range(5):
        await limiter.acquire(rpm=1, tpm=10)
    start = time.monotonic()
    await limiter.acquire(rpm=1, tpm=10)
    elapsed = time.monotonic() - start
    assert elapsed > 0.05


@pytest.mark.asyncio
async def test_limiter_settle():
    limiter = TokenBucketLimiter(rpm=100, tpm=100000, rpm_safety=1.0, tpm_safety=1.0)
    await limiter.acquire(rpm=1, tpm=1500)
    await limiter.settle(estimated_tpm=1500, actual_tpm=1000)
