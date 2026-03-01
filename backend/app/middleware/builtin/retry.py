import asyncio


class ModelRetryMiddleware:
    def __init__(self, max_retries: int = 2, backoff_seconds: float = 0.5):
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

    async def run(self, fn, *args, **kwargs):
        for attempt in range(self.max_retries + 1):
            try:
                return await fn(*args, **kwargs)
            except Exception:
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(self.backoff_seconds * (2 ** attempt))
