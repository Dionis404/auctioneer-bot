import httpx
import pytest
import respx
from httpx import Response

from app import llm_flavor


@pytest.fixture(autouse=True)
def _reset_client():
    yield
    import asyncio

    asyncio.run(llm_flavor.close_client())


async def test_returns_none_without_api_key():
    result = await llm_flavor.generate_flavor_line(None, "context")

    assert result is None


@respx.mock
async def test_returns_stripped_line_on_success():
    respx.post("https://routerai.ru/api/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={"choices": [{"message": {"content": "  Азарт зашкаливает!  "}}]},
        )
    )

    result = await llm_flavor.generate_flavor_line("key", "context")

    assert result == "Азарт зашкаливает!"


@respx.mock
async def test_sends_bearer_auth_and_model():
    route = respx.post("https://routerai.ru/api/v1/chat/completions").mock(
        return_value=Response(
            200, json={"choices": [{"message": {"content": "line"}}]}
        )
    )

    await llm_flavor.generate_flavor_line("secret-key", "context")

    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer secret-key"
    import json

    body = json.loads(request.content)
    assert body["model"] == llm_flavor.MODEL


@respx.mock
async def test_returns_none_on_http_error():
    respx.post("https://routerai.ru/api/v1/chat/completions").mock(
        return_value=Response(500)
    )

    result = await llm_flavor.generate_flavor_line("key", "context")

    assert result is None


@respx.mock
async def test_returns_none_on_timeout():
    respx.post("https://routerai.ru/api/v1/chat/completions").mock(
        side_effect=httpx.TimeoutException("timed out")
    )

    result = await llm_flavor.generate_flavor_line("key", "context")

    assert result is None


@respx.mock
async def test_returns_none_on_empty_content():
    respx.post("https://routerai.ru/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "   "}}]})
    )

    result = await llm_flavor.generate_flavor_line("key", "context")

    assert result is None
