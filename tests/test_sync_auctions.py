import json
from unittest.mock import AsyncMock

import pytest
import respx
from httpx import Response

from app import sfl_client, sync

NFT_ITEM = {
    "auctionId": "auction-nft-1",
    "nft": "Genie Lamp",
    "type": "nft",
    "supply": 50,
    "sfl": 100,
    "startAt": 1_700_000_000_000,
    "endAt": 1_700_003_600_000,
    "chapterLimit": 1,
    "startId": 12345,
}

WEARABLE_ITEM = {
    "auctionId": "auction-wearable-1",
    "wearable": "Goblin Mask",
    "type": "wearable",
    "supply": 200,
    "sfl": 25,
    "ingredients": {"Wood": 10, "Stone": 5},
    "startAt": 1_700_100_000_000,
    "endAt": 1_700_103_600_000,
    "chapterLimit": 2,
}

AUCTIONS_RESPONSE = {
    "auctions": {
        "auctions": [NFT_ITEM, WEARABLE_ITEM],
        "totalSupply": {"Genie Lamp": 500, "Goblin Mask": 2000},
    }
}


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.transaction = self._transaction

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if "INSERT INTO auctions" in query:
            return "INSERT 0 1"
        if "INSERT INTO item_total_supply" in query:
            return "INSERT 0 1"
        return "UPDATE 1"

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
async def test_sync_auctions_maps_nft_and_wearable_fields():
    respx.get("https://api.sunflower-land.com/auctions").mock(
        return_value=Response(200, json=AUCTIONS_RESPONSE)
    )

    conn = FakeConnection()
    pool = FakePool(conn)

    affected = await sync.sync_auctions(pool, auth_token="test-token")

    assert affected == 2

    auction_calls = [c for c in conn.executed if "INSERT INTO auctions" in c[0]]
    assert len(auction_calls) == 2

    nft_args = auction_calls[0][1]
    assert nft_args[0] == "auction-nft-1"
    assert nft_args[1] == "Genie Lamp"
    assert nft_args[2] == "nft"
    assert nft_args[3] == 50
    assert nft_args[4] == 100
    assert nft_args[5] is None
    assert nft_args[8] == 1
    assert nft_args[9] == 12345
    assert json.loads(nft_args[10]) == NFT_ITEM

    wearable_args = auction_calls[1][1]
    assert wearable_args[0] == "auction-wearable-1"
    assert wearable_args[1] == "Goblin Mask"
    assert wearable_args[2] == "wearable"
    assert json.loads(wearable_args[5]) == {"Wood": 10, "Stone": 5}
    assert wearable_args[9] is None
    assert json.loads(wearable_args[10]) == WEARABLE_ITEM

    supply_calls = [c for c in conn.executed if "item_total_supply" in c[0]]
    assert len(supply_calls) == 2
    supply_pairs = {args[0]: args[1] for _, args in supply_calls}
    assert supply_pairs == {"Genie Lamp": 500, "Goblin Mask": 2000}


@respx.mock
async def test_fetch_auctions_raises_auth_expired_on_401():
    respx.get("https://api.sunflower-land.com/auctions").mock(
        return_value=Response(401, json={"error": "expired"})
    )

    with pytest.raises(sfl_client.AuthExpiredError):
        await sfl_client.fetch_auctions("bad-token")


@respx.mock
async def test_fetch_auction_results_returns_none_on_404():
    respx.get(
        "https://api.sunflower-land.com/auction/auction-1/results/farm-1"
    ).mock(return_value=Response(404, json={"error": "not ready"}))

    result = await sfl_client.fetch_auction_results("auction-1", "farm-1", "token")

    assert result is None


@respx.mock
async def test_fetch_auction_results_raises_auth_expired_on_401():
    respx.get(
        "https://api.sunflower-land.com/auction/auction-1/results/farm-1"
    ).mock(return_value=Response(401, json={"error": "expired"}))

    with pytest.raises(sfl_client.AuthExpiredError):
        await sfl_client.fetch_auction_results("auction-1", "farm-1", "token")


@respx.mock
async def test_sync_results_upserts_and_marks_fetched():
    respx.get(
        "https://api.sunflower-land.com/auction/auction-1/results/farm-1"
    ).mock(
        return_value=Response(
            200,
            json={
                "status": "winner",
                "participantCount": 42,
                "supply": 50,
                "leaderboard": [{"farmId": "farm-1", "rank": 1}],
                "endAt": 1_700_000_000_000,
            },
        )
    )

    conn = FakeConnection()
    pool = FakePool(conn)

    ok = await sync.sync_results(pool, "auction-1", "farm-1", auth_token="token")

    assert ok is True
    result_calls = [c for c in conn.executed if "auction_results" in c[0]]
    assert len(result_calls) == 1
    args = result_calls[0][1]
    assert args[0] == "auction-1"
    assert args[1] == "winner"
    assert args[2] == 42
    assert args[3] == 50
    assert json.loads(args[4]) == [{"farmId": "farm-1", "rank": 1}]

    update_calls = [c for c in conn.executed if "UPDATE auctions" in c[0]]
    assert len(update_calls) == 1
    assert update_calls[0][1] == ("auction-1",)


@respx.mock
async def test_sync_results_returns_false_when_not_ready():
    respx.get(
        "https://api.sunflower-land.com/auction/auction-1/results/farm-1"
    ).mock(return_value=Response(404))

    conn = FakeConnection()
    pool = FakePool(conn)

    ok = await sync.sync_results(pool, "auction-1", "farm-1", auth_token="token")

    assert ok is False
    assert conn.executed == []
