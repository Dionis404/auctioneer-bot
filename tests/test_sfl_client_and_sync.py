from unittest.mock import AsyncMock

import pytest
import respx
from httpx import HTTPStatusError, Response

from app import sfl_client, sync
from app.jobs.notifications import format_top_and_last

COMPLETE_RESPONSE = {
    "data": {
        "status": "complete",
        "participantCount": 136,
        "supply": 15,
        "leaderboard": [
            {
                "experience": 187716722.19022888,
                "farmId": 129896,
                "items": {"Floater": 13448},
                "sfl": 0,
                "rank": 1,
                "tickets": 13448,
                "username": "AVF",
            },
            {
                "experience": 2486892.325,
                "farmId": 490995961471682,
                "items": {"Floater": 6419},
                "sfl": 0,
                "rank": 2,
                "tickets": 6419,
                "username": "SypusM",
            },
            {
                "experience": 57467159.211695045,
                "farmId": 442741547533563,
                "items": {"Floater": 5800},
                "sfl": 0,
                "rank": 3,
                "tickets": 5800,
                "username": "nekodesu",
            },
            {
                "experience": 7522037.80075001,
                "farmId": 6347816418067468,
                "items": {"Floater": 4711},
                "sfl": 0,
                "rank": 15,
                "tickets": 4711,
                "username": "Amadeus444",
            },
        ],
        "endAt": 1_775_726_400_000,
    }
}

PENDING_RESPONSE = {
    "data": {
        "status": "pending",
        "supply": 15,
        "leaderboard": [],
        "endAt": 1_775_726_400_000,
    }
}

AUCTIONS_LIST_RESPONSE = {
    "data": {
        "auctions": [
            {
                "auctionId": "coin-aura-2024-08-07-drop-1",
                "type": "wearable",
                "wearable": "Coin Aura",
                "startAt": 1_723_017_600_000,
                "endAt": 1_723_021_200_000,
                "supply": 1,
                "sfl": 1,
                "ingredients": {},
                "chapterLimit": 1,
            },
            {
                "auctionId": "pet-2025-10-08-drop-1",
                "type": "nft",
                "nft": "Pet",
                "startId": 2,
                "startAt": 1_759_895_880_000,
                "endAt": 1_759_899_480_000,
                "supply": 10,
                "sfl": 1,
                "ingredients": {"Gold": 5},
                "chapterLimit": 7,
            },
        ],
        "totalSupply": {"Coin Aura": 100, "Rocket Onesie": 250},
    }
}


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.transaction = self._transaction

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "INSERT 0 1"

    def _transaction(self):
        return _NullContext()


class _NullContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireContext(self._conn)


class _AcquireContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _reset_client():
    yield
    import asyncio

    asyncio.run(sfl_client.close_client())


@respx.mock
async def test_fetch_auction_results_sends_x_api_key_header_and_query_param():
    route = respx.get("https://api.sunflower-land.com/community/data").mock(
        return_value=Response(200, json=COMPLETE_RESPONSE)
    )

    result = await sfl_client.fetch_auction_results("auction-1", "my-key")

    assert route.called
    request = route.calls[0].request
    assert request.headers["x-api-key"] == "my-key"
    assert request.url.params["type"] == "auctionResults"
    assert request.url.params["auctionId"] == "auction-1"
    assert result == COMPLETE_RESPONSE["data"]


@respx.mock
async def test_fetch_auction_results_raises_auth_expired_on_401():
    respx.get("https://api.sunflower-land.com/community/data").mock(
        return_value=Response(401, json={"error": "invalid key"})
    )

    with pytest.raises(sfl_client.AuthExpiredError):
        await sfl_client.fetch_auction_results("auction-1", "bad-key")


@respx.mock
async def test_fetch_auction_results_returns_none_on_404():
    respx.get("https://api.sunflower-land.com/community/data").mock(
        return_value=Response(404, json={"error": "not found"})
    )

    result = await sfl_client.fetch_auction_results("unknown-auction", "key")

    assert result is None


@respx.mock
async def test_sync_results_complete_status_saves_and_returns_true():
    respx.get("https://api.sunflower-land.com/community/data").mock(
        return_value=Response(200, json=COMPLETE_RESPONSE)
    )

    conn = FakeConnection()
    pool = FakePool(conn)

    ok = await sync.sync_results(pool, "auction-1", api_key="key")

    assert ok is True
    result_calls = [c for c in conn.executed if "auction_results" in c[0]]
    assert len(result_calls) == 1
    args = result_calls[0][1]
    assert args[0] == "auction-1"
    assert args[1] == "complete"
    assert args[2] == 136
    assert args[3] == 15
    assert args[4] == COMPLETE_RESPONSE["data"]["leaderboard"]

    update_calls = [c for c in conn.executed if "UPDATE auctions" in c[0]]
    assert len(update_calls) == 1
    assert update_calls[0][1] == ("auction-1",)


@respx.mock
async def test_sync_results_pending_status_returns_false_without_writing():
    respx.get("https://api.sunflower-land.com/community/data").mock(
        return_value=Response(200, json=PENDING_RESPONSE)
    )

    conn = FakeConnection()
    pool = FakePool(conn)

    ok = await sync.sync_results(pool, "auction-1", api_key="key")

    assert ok is False
    assert conn.executed == []


@respx.mock
async def test_sync_results_returns_false_on_404():
    respx.get("https://api.sunflower-land.com/community/data").mock(
        return_value=Response(404)
    )

    conn = FakeConnection()
    pool = FakePool(conn)

    ok = await sync.sync_results(pool, "auction-1", api_key="key")

    assert ok is False
    assert conn.executed == []


@respx.mock
async def test_fetch_auctions_sends_x_api_key_header_and_query_param():
    route = respx.get("https://api.sunflower-land.com/community/data").mock(
        return_value=Response(200, json=AUCTIONS_LIST_RESPONSE)
    )

    result = await sfl_client.fetch_auctions("my-key")

    assert route.called
    request = route.calls[0].request
    assert request.headers["x-api-key"] == "my-key"
    assert request.url.params["type"] == "auctions"
    assert result == AUCTIONS_LIST_RESPONSE["data"]


@respx.mock
async def test_fetch_auctions_raises_auth_expired_on_401():
    respx.get("https://api.sunflower-land.com/community/data").mock(
        return_value=Response(401, json={"error": "invalid key"})
    )

    with pytest.raises(sfl_client.AuthExpiredError):
        await sfl_client.fetch_auctions("bad-key")


@respx.mock
async def test_fetch_auctions_retries_on_429_then_succeeds(monkeypatch):
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(sfl_client.asyncio, "sleep", fake_sleep)

    route = respx.get("https://api.sunflower-land.com/community/data").mock(
        side_effect=[
            Response(429),
            Response(429),
            Response(200, json=AUCTIONS_LIST_RESPONSE),
        ]
    )

    result = await sfl_client.fetch_auctions("key")

    assert route.call_count == 3
    assert sleep_calls == [5, 10]
    assert result == AUCTIONS_LIST_RESPONSE["data"]


@respx.mock
async def test_fetch_auctions_raises_after_exhausting_429_retries(monkeypatch):
    async def fake_sleep(seconds):
        pass

    monkeypatch.setattr(sfl_client.asyncio, "sleep", fake_sleep)

    respx.get("https://api.sunflower-land.com/community/data").mock(
        return_value=Response(429)
    )

    with pytest.raises(HTTPStatusError):
        await sfl_client.fetch_auctions("key")


@respx.mock
async def test_sync_auctions_maps_wearable_and_nft_fields():
    respx.get("https://api.sunflower-land.com/community/data").mock(
        return_value=Response(200, json=AUCTIONS_LIST_RESPONSE)
    )

    conn = FakeConnection()
    pool = FakePool(conn)

    affected = await sync.sync_auctions(pool, api_key="key")

    assert affected == 2

    auction_calls = [c for c in conn.executed if "INSERT INTO auctions" in c[0]]
    assert len(auction_calls) == 2

    wearable_args = auction_calls[0][1]
    assert wearable_args[0] == "coin-aura-2024-08-07-drop-1"
    assert wearable_args[1] == "Coin Aura"
    assert wearable_args[2] == "wearable"
    assert wearable_args[3] == 1
    assert wearable_args[4] == 1
    assert wearable_args[9] is None  # startId absent for wearables

    nft_args = auction_calls[1][1]
    assert nft_args[0] == "pet-2025-10-08-drop-1"
    assert nft_args[1] == "Pet"
    assert nft_args[2] == "nft"
    assert nft_args[5] == {"Gold": 5}
    assert nft_args[9] == 2

    supply_calls = [c for c in conn.executed if "item_total_supply" in c[0]]
    assert len(supply_calls) == 2


def test_format_top_and_last_with_missing_farm_in_leaderboard():
    # A farm we track isn't present in the leaderboard at all — formatting
    # must not crash, it just won't show that farm (no personal status anymore).
    leaderboard = COMPLETE_RESPONSE["data"]["leaderboard"]
    tracked_farm_id = 999999999  # not present in any entry

    present_farm_ids = {entry["farmId"] for entry in leaderboard}
    assert tracked_farm_id not in present_farm_ids

    result = format_top_and_last(leaderboard)

    assert "AVF" in result
    assert "Amadeus444" in result


def test_format_top_and_last_handles_missing_username():
    leaderboard = [
        {"rank": 1, "farmId": 111, "sfl": 0, "items": {"Floater": 100}},
        {"rank": 2, "farmId": 222, "username": None, "sfl": 0, "items": {"Floater": 50}},
    ]

    result = format_top_and_last(leaderboard)

    lines = result.split("\n")
    assert len(lines) == 2
    assert "без ника" in lines[0]
    assert "без ника" in lines[1]
