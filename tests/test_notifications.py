from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest

from app.jobs.notifications import (
    delete_notification,
    format_bid,
    format_msk_time,
    format_top_and_last,
    send_auction_ended_fallback,
    send_reminder,
    send_results_notification,
    send_started,
)


def test_format_msk_time_converts_utc_to_moscow():
    dt = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)

    result = format_msk_time(dt)

    assert result == "02.08 13:00 МСК"


def test_format_bid_uses_flower_when_sfl_price_flag_is_true():
    assert format_bid(1, None) == "Ставка: Flower"


def test_format_bid_lists_enabled_ingredients_when_sfl_flag_is_false():
    assert format_bid(0, {"Gem": 1, "Wood": 0}) == "Ставка: Gem"


def test_format_bid_dash_when_no_price_or_ingredients():
    assert format_bid(0, None) == "Ставка: —"


def test_format_top_and_last_shows_all_entries_sorted_by_rank():
    leaderboard = [
        {"rank": 50, "username": "Dozach007", "sfl": 0, "items": {"Salt Rock": 6108}},
        {"rank": 1, "username": "Diana", "sfl": 0, "items": {"Salt Rock": 9597}},
        {"rank": 2, "username": "Zolkan", "sfl": 0, "items": {"Salt Rock": 9185}},
        {"rank": 3, "username": "Bolt", "sfl": 0, "items": {"Salt Rock": 8600}},
    ]

    result = format_top_and_last(leaderboard)

    lines = result.split("\n")
    assert len(lines) == 4
    assert lines[0] == "1. Diana — 9597 Salt Rock"
    assert lines[-1] == "50. Dozach007 — 6108 Salt Rock"


def test_format_top_and_last_shows_flower_bid():
    leaderboard = [{"rank": 1, "username": "Diana", "sfl": 100, "items": None}]

    result = format_top_and_last(leaderboard)

    assert result == "1. Diana — 100 Flower"


def test_format_top_and_last_no_data_message_when_empty():
    assert format_top_and_last([]) == "нет данных"


def test_format_top_and_last_parses_double_encoded_json_string():
    import json

    leaderboard_str = json.dumps(
        [{"rank": 1, "username": "Diana", "sfl": 100, "items": None}]
    )

    result = format_top_and_last(leaderboard_str)

    assert result == "1. Diana — 100 Flower"


def test_format_bid_parses_double_encoded_json_string():
    import json

    ingredients_str = json.dumps({"Gem": 1, "Wood": 0})

    assert format_bid(0, ingredients_str) == "Ставка: Gem"


class FakePool:
    def __init__(self, item_name):
        self._item_name = item_name
        self.executed = []

    async def fetchrow(self, query, *args):
        return {"item_name": self._item_name}

    async def execute(self, query, *args):
        self.executed.append((query, args))


async def test_send_auction_ended_fallback_sends_and_records():
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 4242
    pool = FakePool("Genie Lamp")

    await send_auction_ended_fallback(bot, pool, "auction-1", chat_id=777)

    bot.send_message.assert_awaited_once()
    chat_id, text = bot.send_message.await_args.args
    assert chat_id == 777
    assert "Genie Lamp" in text
    assert "🏁" in text

    assert len(pool.executed) == 1
    query, args = pool.executed[0]
    assert "ended_fallback" in query
    assert args == ("auction-1", 777, 4242)


async def test_send_auction_ended_fallback_noop_without_notify_chat_id():
    bot = AsyncMock()
    pool = FakePool("Genie Lamp")

    await send_auction_ended_fallback(bot, pool, "auction-1", chat_id=None)

    bot.send_message.assert_not_called()
    assert pool.executed == []


class FakeAuctionPool:
    """Fake pool for send_reminder / send_started, backed by an auctions row."""

    def __init__(self, row, sprite_row=None):
        self._row = row
        self._sprite_row = sprite_row
        self.executed = []

    async def fetchrow(self, query, *args):
        if "sfl_items" in query:
            return self._sprite_row
        return self._row

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "INSERT 0 1"


def _patch_notify_chat_id(monkeypatch, value):
    import app.jobs.notifications as notifications

    monkeypatch.setattr(notifications, "_notify_chat_id", lambda: value)


async def test_send_reminder_zero_price_uses_ingredients(monkeypatch):
    _patch_notify_chat_id(monkeypatch, 555)

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 111
    start_at = datetime.now(timezone.utc) + timedelta(hours=1)
    row = {
        "item_name": "Goblin Mask",
        "item_type": "wearable",
        "supply": 200,
        "sfl_price": 0,
        "ingredients": {"Gem": 1, "Wood": 0},
        "start_at": start_at,
    }
    pool = FakeAuctionPool(row)

    await send_reminder(bot, pool, "auction-1")

    bot.send_photo.assert_awaited_once()
    _, kwargs = bot.send_photo.await_args
    assert kwargs["show_caption_above_media"] is True
    assert kwargs["photo"]  # falls back to default image
    text = kwargs["caption"]
    assert "Goblin Mask" in text
    assert "Ставка: Gem" in text
    assert "Wood" not in text

    insert_calls = [c for c in pool.executed if "reminder_1h" in c[0]]
    assert len(insert_calls) == 1
    args = insert_calls[0][1]
    assert args == ("auction-1", 555, 111, start_at)


async def test_send_reminder_sfl_flag_true(monkeypatch):
    _patch_notify_chat_id(monkeypatch, 555)

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 222
    row = {
        "item_name": "Genie Lamp",
        "item_type": "nft",
        "supply": 50,
        "sfl_price": 1,
        "ingredients": None,
        "start_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    pool = FakeAuctionPool(row)

    await send_reminder(bot, pool, "auction-2")

    text = bot.send_photo.await_args.kwargs["caption"]
    assert "Ставка: Flower" in text


async def test_send_reminder_noop_without_notify_chat_id(monkeypatch):
    _patch_notify_chat_id(monkeypatch, None)

    bot = AsyncMock()
    pool = FakeAuctionPool({"item_name": "x", "item_type": "nft"})

    await send_reminder(bot, pool, "auction-1")

    bot.send_photo.assert_not_called()


async def test_send_started_sends_photo_and_records(monkeypatch):
    _patch_notify_chat_id(monkeypatch, 555)

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 333
    end_at = datetime.now(timezone.utc) + timedelta(hours=1)
    row = {"item_name": "Goblin Mask", "item_type": "wearable", "end_at": end_at}
    pool = FakeAuctionPool(row)

    await send_started(bot, pool, "auction-1")

    text = bot.send_photo.await_args.kwargs["caption"]
    assert "Goblin Mask" in text
    assert "🔨" in text

    insert_calls = [c for c in pool.executed if "'started'" in c[0]]
    assert len(insert_calls) == 1
    assert insert_calls[0][1] == ("auction-1", 555, 333, end_at)


class FakeResultsPool:
    def __init__(self, row):
        self._row = row
        self.executed = []

    async def fetchrow(self, query, *args):
        if "sfl_items" in query:
            return None
        return self._row

    async def execute(self, query, *args):
        self.executed.append((query, args))


async def test_send_results_notification_shows_top3_and_last(monkeypatch):
    _patch_notify_chat_id(monkeypatch, 555)

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 444
    row = {
        "item_name": "Genie Lamp",
        "item_type": "nft",
        "my_status": "loser",
        "participant_count": 275,
        "leaderboard": [
            {"rank": 1, "username": "alice", "tickets": 10},
            {"rank": 2, "username": "bob", "tickets": 8},
            {"rank": 3, "username": "carol", "tickets": 5},
            {"rank": 50, "username": "dave", "tickets": 1},
        ],
    }
    pool = FakeResultsPool(row)

    await send_results_notification(bot, pool, "auction-1")

    text = bot.send_photo.await_args.kwargs["caption"]
    assert "Статус" not in text
    assert "275" in text
    assert "alice" in text
    assert "carol" in text
    assert "dave" in text  # last place is shown too

    insert_calls = [c for c in pool.executed if "results" in c[0]]
    assert len(insert_calls) == 1
    assert insert_calls[0][1] == ("auction-1", 555, 444)


class FakeDeletePool:
    def __init__(self, row):
        self._row = row
        self.executed = []

    async def fetchrow(self, query, *args):
        return self._row

    async def execute(self, query, *args):
        self.executed.append((query, args))


async def test_delete_notification_deletes_and_marks():
    bot = AsyncMock()
    pool = FakeDeletePool({"chat_id": 555, "message_id": 111})

    await delete_notification(bot, pool, "auction-1", "reminder_1h")

    bot.delete_message.assert_awaited_once_with(555, 111)
    assert len(pool.executed) == 1
    assert pool.executed[0][1] == ("auction-1", "reminder_1h")


async def test_delete_notification_returns_if_not_found():
    bot = AsyncMock()
    pool = FakeDeletePool(None)

    await delete_notification(bot, pool, "auction-1", "reminder_1h")

    bot.delete_message.assert_not_called()
    assert pool.executed == []


async def test_delete_notification_handles_already_deleted_message():
    bot = AsyncMock()
    bot.delete_message.side_effect = TelegramBadRequest(
        method=AsyncMock(), message="message to delete not found"
    )
    pool = FakeDeletePool({"chat_id": 555, "message_id": 111})

    await delete_notification(bot, pool, "auction-1", "started")

    assert len(pool.executed) == 1
