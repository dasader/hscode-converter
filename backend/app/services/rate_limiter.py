import asyncio
import time


class TokenBucket:
    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    async def consume(self, amount: float) -> bool:
        async with self._lock:
            self._refill()
            if self.tokens >= amount:
                self.tokens -= amount
                return True
            return False

    async def return_tokens(self, amount: float):
        async with self._lock:
            self.tokens = min(self.capacity, self.tokens + amount)


class TokenBucketLimiter:
    def __init__(self, rpm: int = 500, tpm: int = 500000,
                 rpm_safety: float = 0.8, tpm_safety: float = 0.8):
        effective_rpm = rpm * rpm_safety
        effective_tpm = tpm * tpm_safety
        self.rpm_bucket = TokenBucket(capacity=effective_rpm, refill_rate=effective_rpm / 60.0)
        self.tpm_bucket = TokenBucket(capacity=effective_tpm, refill_rate=effective_tpm / 60.0)

    async def acquire(self, rpm: int = 1, tpm: int = 0):
        while True:
            rpm_ok = await self.rpm_bucket.consume(rpm)
            if not rpm_ok:
                await asyncio.sleep(0.1)
                continue
            tpm_ok = await self.tpm_bucket.consume(tpm)
            if not tpm_ok:
                await self.rpm_bucket.return_tokens(rpm)
                await asyncio.sleep(0.1)
                continue
            return

    async def settle(self, estimated_tpm: int, actual_tpm: int):
        diff = estimated_tpm - actual_tpm
        if diff > 0:
            await self.tpm_bucket.return_tokens(diff)
