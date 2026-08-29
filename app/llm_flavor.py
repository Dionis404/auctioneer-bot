import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://routerai.ru/api/v1"
MODEL = "google/gemini-2.5-flash-lite"
TIMEOUT = 8.0

SYSTEM_PROMPT = (
    "Ты — весёлый ведущий аукционов в игре Sunflower Land. "
    "Придумай ОДНУ короткую живую фразу (не больше 12 слов) на русском языке "
    "для уведомления об аукционе, по контексту события. Без эмодзи, без кавычек, "
    "без markdown-разметки, без обращения по имени. Верни только саму фразу."
)

_client: httpx.AsyncClient | None = None


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


async def generate_flavor_line(api_key: str | None, context: str) -> str | None:
    """Ask the LLM for one short flavor line to accompany a notification.

    Returns None on any failure (missing key, network error, bad response) so
    callers can fall back to the plain templated text.
    """
    if not api_key:
        return None

    client = _get_client()

    try:
        response = await client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
                "max_tokens": 60,
                "temperature": 1.0,
            },
        )
        response.raise_for_status()
        data = response.json()
        line = data["choices"][0]["message"]["content"].strip()
        return line or None
    except Exception:
        logger.exception("generate_flavor_line: failed, falling back to plain text")
        return None
