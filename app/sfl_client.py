import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sunflower-land.com"
TIMEOUT = 10.0

# Community API rate limit is ~1 request/5s per IP (doubling to 10s if hammered).
RATE_LIMIT_RETRY_DELAYS_SECONDS = [5, 10, 15, 30]

_client: httpx.AsyncClient | None = None


class AuthExpiredError(Exception):
    pass


def _headers(api_key: str | None) -> dict[str, str]:
    return {"x-api-key": api_key or ""}


def init_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _get_client() -> httpx.AsyncClient:
    return _client if _client is not None else init_client()


async def fetch_auctions(api_key: str | None) -> dict:
    client = _get_client()

    for attempt, delay in enumerate([0, *RATE_LIMIT_RETRY_DELAYS_SECONDS]):
        if delay:
            logger.warning(
                "fetch_auctions rate limited (429), retrying in %ss (attempt %s)",
                delay,
                attempt,
            )
            await asyncio.sleep(delay)

        response = await client.get(
            "/community/data",
            params={"type": "auctions"},
            headers=_headers(api_key),
        )

        if response.status_code == 401:
            raise AuthExpiredError("SFL API key rejected (401) for auctions")

        if response.status_code == 429:
            continue

        if response.status_code != 200:
            logger.error(
                "fetch_auctions failed: status=%s body=%s",
                response.status_code,
                response.text,
            )
            response.raise_for_status()

        return response.json().get("data", {})

    logger.error("fetch_auctions failed: still rate limited after all retries")
    response.raise_for_status()


async def fetch_auction_results(auction_id: str, api_key: str | None) -> dict | None:
    client = _get_client()
    response = await client.get(
        "/community/data",
        params={"type": "auctionResults", "auctionId": auction_id},
        headers=_headers(api_key),
    )

    if response.status_code == 401:
        raise AuthExpiredError("SFL API key rejected (401) for auctionResults")

    if response.status_code != 200:
        logger.debug(
            "fetch_auction_results not ready: auction_id=%s status=%s body=%s",
            auction_id,
            response.status_code,
            response.text,
        )
        return None

    return response.json().get("data")
