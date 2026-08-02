from unittest.mock import AsyncMock, MagicMock

from app.config import Config
from app.handlers.commands import cmd_test_notification


def _make_config(**overrides) -> Config:
    base = dict(
        telegram_bot_token="t",
        database_url="postgresql://x",
        sfl_auth_token="token",
        sfl_farm_id="farm-1",
        alert_chat_id=1,
        notify_chat_id=999,
        admin_ids=[42],
    )
    base.update(overrides)
    return Config(**base)


def _make_message(user_id: int = 42) -> MagicMock:
    message = MagicMock()
    message.from_user.id = user_id
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
    command = MagicMock(args=None)
    bot = AsyncMock()
    pool = FakePool({"item_name": "Genie Lamp", "item_type": "nft"})
    config = _make_config()

    await cmd_test_notification(message, command, bot, pool, config)

    bot.send_photo.assert_not_called()
    message.answer.assert_not_called()


async def test_unknown_type_lists_options():
    message = _make_message()
    command = MagicMock(args="bogus")
    bot = AsyncMock()
    pool = FakePool({"item_name": "Genie Lamp", "item_type": "nft"})
    config = _make_config()

    await cmd_test_notification(message, command, bot, pool, config)

    bot.send_photo.assert_not_called()
    message.answer.assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "reminder" in text and "started" in text and "results" in text


async def test_no_auctions_in_db():
    message = _make_message()
    command = MagicMock(args="reminder")
    bot = AsyncMock()
    pool = FakePool(None)
    config = _make_config()

    await cmd_test_notification(message, command, bot, pool, config)

    bot.send_photo.assert_not_called()
    message.answer.assert_awaited_once()


async def test_reminder_sends_photo_with_item_name():
    message = _make_message()
    command = MagicMock(args="reminder")
    bot = AsyncMock()
    pool = FakePool(
        {"item_name": "Genie Lamp", "item_type": "nft"},
        sprite_row={"sprite": "sfts/genie_lamp.webp"},
    )
    config = _make_config()

    await cmd_test_notification(message, command, bot, pool, config)

    bot.send_photo.assert_awaited_once()
    _, kwargs = bot.send_photo.await_args
    assert kwargs["photo"] == "https://goblincodex.fun/sprites/sfts/genie_lamp.webp"
    assert kwargs["show_caption_above_media"] is True
    assert "Genie Lamp" in kwargs["caption"]
    message.answer.assert_awaited_once()


async def test_reminder_falls_back_to_default_image_when_sprite_missing():
    message = _make_message()
    command = MagicMock(args="reminder")
    bot = AsyncMock()
    pool = FakePool({"item_name": "Genie Lamp", "item_type": "nft"}, sprite_row=None)
    config = _make_config()

    await cmd_test_notification(message, command, bot, pool, config)

    _, kwargs = bot.send_photo.await_args
    assert kwargs["photo"] == "https://goblincodex.fun/sprites/sfts/alba.webp"


async def test_results_includes_leaderboard():
    message = _make_message()
    command = MagicMock(args="results")
    bot = AsyncMock()
    pool = FakePool({"item_name": "Goblin Mask", "item_type": "wearable"})
    config = _make_config()

    await cmd_test_notification(message, command, bot, pool, config)

    text = bot.send_photo.await_args.kwargs["caption"]
    assert "test_user_1" in text
    assert "Статус" not in text


async def test_missing_notify_chat_id():
    message = _make_message()
    command = MagicMock(args="started")
    bot = AsyncMock()
    pool = FakePool({"item_name": "Genie Lamp", "item_type": "nft"})
    config = _make_config(notify_chat_id=None)

    await cmd_test_notification(message, command, bot, pool, config)

    bot.send_photo.assert_not_called()
    message.answer.assert_awaited_once()
