from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Config
from app.handlers.commands import cmd_next_auction


@pytest.fixture(autouse=True)
def _mock_background_compose(monkeypatch):
    async def fake_render(image_url, background_key):
        return b"fake-png-bytes"

    monkeypatch.setattr(
        "app.jobs.notifications.render_item_on_background", fake_render
    )


def _make_config(**overrides) -> Config:
    base = dict(
        telegram_bot_token="t",
        database_url="postgresql://x",
        sfl_api_key="key",
        alert_chat_id=1,
        notify_chat_id=999,
        admin_ids=[42],
    )
    base.update(overrides)
    return Config(**base)


def _make_message(user_id: int = 42, chat_id: int = 555) -> MagicMock:
    message = MagicMock()
    message.from_user.id = user_id
    message.chat.id = chat_id
    message.answer = AsyncMock()
    return message


class FakePool:
    def __init__(self, row, sprite_row=None):
        self._row = row
        self._sprite_row = sprite_row

    async def fetchrow(self, query, *args):
        if "sfl_items" in query:
            return self._sprite_row
        return self._row


async def test_rejects_non_admin():
    message = _make_message(user_id=1)
    bot = AsyncMock()
    pool = FakePool({"item_name": "Genie Lamp", "item_type": "nft"})
    config = _make_config()

    await cmd_next_auction(message, bot, pool, config)

    bot.send_photo.assert_not_called()
    message.answer.assert_not_called()


async def test_no_upcoming_auctions():
    message = _make_message()
    bot = AsyncMock()
    pool = FakePool(None)
    config = _make_config()

    await cmd_next_auction(message, bot, pool, config)

    bot.send_photo.assert_not_called()
    message.answer.assert_awaited_once_with("Нет запланированных аукционов.")


async def test_sends_next_auction_to_calling_chat():
    message = _make_message(chat_id=777)
    bot = AsyncMock()
    start_at = datetime.now(timezone.utc) + timedelta(hours=2)
    row = {
        "item_name": "Genie Lamp",
        "item_type": "nft",
        "supply": 50,
        "sfl_price": 1,
        "ingredients": None,
        "start_at": start_at,
    }
    pool = FakePool(row, sprite_row={"sprite": "sfts/genie_lamp.webp"})
    config = _make_config()

    await cmd_next_auction(message, bot, pool, config)

    bot.send_photo.assert_awaited_once()
    _, kwargs = bot.send_photo.await_args
    assert kwargs["show_caption_above_media"] is True

    call_args, call_kwargs = bot.send_photo.await_args
    chat_id = call_args[0] if call_args else call_kwargs.get("chat_id")
    assert chat_id == 777  # chat the command was called from

    caption = kwargs["caption"]
    assert "Genie Lamp" in caption
    assert "Ставка: Flower" in caption
    assert "Лотов: 50" in caption

    message.answer.assert_not_called()
