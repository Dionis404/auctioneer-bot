import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sunflower-land.com"
TIMEOUT = 10.0

_client: httpx.AsyncClient | None = None


class AuthExpiredError(Exception):
    pass


def _headers(auth_token: str | None) -> dict[str, str]:
    return {
        "authorization": f"Bearer {auth_token}",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://sunflower-land.com",
        "referer": "https://sunflower-land.com/",
    }


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


async def fetch_auctions(auth_token: str | None) -> dict:
    client = _get_client()
    response = await client.get("/auctions", headers=_headers(auth_token))

    if response.status_code == 401:
        raise AuthExpiredError("SFL auth token expired (fetch_auctions)")

    if response.status_code != 200:
        logger.error(
            "fetch_auctions failed: status=%s body=%s",
            response.status_code,
            response.text,
        )
        response.raise_for_status()

    return response.json()


async def fetch_auction_results(
    auction_id: str, farm_id: str, auth_token: str | None
) -> dict | None:
    client = _get_client()
    response = await client.get(
        f"/auction/{auction_id}/results/{farm_id}",
        headers=_headers(auth_token),
    )

    if response.status_code == 401:
        raise AuthExpiredError("SFL auth token expired (fetch_auction_results)")

    if response.status_code != 200:
        logger.debug(
            "fetch_auction_results not ready: auction_id=%s status=%s body=%s",
            auction_id,
            response.status_code,
            response.text,
        )
        return None

    return response.json()
