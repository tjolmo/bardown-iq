import asyncio
import logging
import httpx

logger = logging.getLogger(__name__)

# max simultaneous requests when fanning out over teams / players (be polite to the NHL API)
DEFAULT_CONCURRENCY = 6
RETRY_STATUSES = {429, 500, 502, 503, 504}

_client: httpx.AsyncClient | None = None

def get_client() -> httpx.AsyncClient:
    """Shared client, created lazily so connections (and TLS sessions) are reused across requests."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=True,
        )
    return _client

async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None

async def get_with_retries(url: str, params: dict | None = None, retries: int = 3, backoff: float = 1.0) -> httpx.Response:
    """GET via the shared client, retrying timeouts/connection errors and 429/5xx with exponential backoff.
    Returns the final response (callers still call raise_for_status); re-raises the last transport error."""
    for attempt in range(retries + 1):
        try:
            response = await get_client().get(url, params=params)
        except httpx.TransportError as e:
            if attempt == retries:
                raise
            reason = repr(e)
        else:
            if response.status_code not in RETRY_STATUSES or attempt == retries:
                return response
            reason = f"HTTP {response.status_code}"
        delay = backoff * 2 ** attempt
        logger.warning("GET %s failed (%s), retry %d/%d in %.1fs", url, reason, attempt + 1, retries, delay)
        await asyncio.sleep(delay)

async def gather_bounded(coros, limit: int = DEFAULT_CONCURRENCY) -> list:
    """Runs coroutines concurrently, at most `limit` at a time. Results keep input order."""
    semaphore = asyncio.Semaphore(limit)

    async def run(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(run(c) for c in coros))
