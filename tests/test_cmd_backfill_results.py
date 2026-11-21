from unittest.mock import AsyncMock, MagicMock

from app.config import Config
from app.handlers.commands import cmd_backfill_results


def _make_config(**overrides) -> Config:
    base = dict(
        telegram_bot_token="t",
        database_url="postgresql://x",
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
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows


async def test_rejects_non_admin():
    message = _make_message(user_id=1)
    bot = AsyncMock()
    pool = FakePool([{"auction_id": "a1"}])
    config = _make_config()

    await cmd_backfill_results(message, bot, pool, config)

    message.answer.assert_not_called()


async def test_no_pending_auctions():
    message = _make_message()
    bot = AsyncMock()
    pool = FakePool([])
    config = _make_config()

    await cmd_backfill_results(message, bot, pool, config)

    message.answer.assert_awaited_once_with(
        "Нет завершённых аукционов без результатов."
    )


async def test_reports_pending_count_and_points_to_collector():
    message = _make_message()
    bot = AsyncMock()
    pool = FakePool([{"auction_id": "a1"}, {"auction_id": "a2"}])
    config = _make_config()

    await cmd_backfill_results(message, bot, pool, config)

    text = message.answer.await_args_list[-1].args[0]
    assert "2" in text
    assert "sfl-collector" in text
