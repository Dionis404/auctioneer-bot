from unittest.mock import AsyncMock, MagicMock

from app.config import Config
from app.handlers import commands as commands_module
from app.handlers.commands import cmd_backfill_results
from app.sfl_client import AuthExpiredError


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
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows


async def test_rejects_non_admin():
    message = _make_message(user_id=1)
    pool = FakePool([{"auction_id": "a1"}])
    config = _make_config()

    await cmd_backfill_results(message, pool, config)

    message.answer.assert_not_called()


async def test_no_pending_auctions():
    message = _make_message()
    pool = FakePool([])
    config = _make_config()

    await cmd_backfill_results(message, pool, config)

    message.answer.assert_awaited_once_with(
        "Нет завершённых аукционов без результатов."
    )


async def test_fetches_results_for_each_auction(monkeypatch):
    message = _make_message()
    pool = FakePool([{"auction_id": "a1"}, {"auction_id": "a2"}, {"auction_id": "a3"}])
    config = _make_config()

    sync_results_mock = AsyncMock(side_effect=[True, False, True])
    monkeypatch.setattr(commands_module, "sync_results", sync_results_mock)

    await cmd_backfill_results(message, pool, config)

    assert sync_results_mock.await_count == 3
    sync_results_mock.assert_any_await(pool, "a1", "farm-1", "token")

    final_text = message.answer.await_args_list[-1].args[0]
    assert "Успешно достано: 2" in final_text
    assert "API ещё не отдал" in final_text
    assert "1" in final_text


async def test_stops_on_auth_expired(monkeypatch):
    message = _make_message()
    pool = FakePool([{"auction_id": "a1"}, {"auction_id": "a2"}])
    config = _make_config()

    async def _raise(*args, **kwargs):
        raise AuthExpiredError("expired")

    sync_results_mock = AsyncMock(side_effect=_raise)
    monkeypatch.setattr(commands_module, "sync_results", sync_results_mock)

    await cmd_backfill_results(message, pool, config)

    sync_results_mock.assert_awaited_once()
    final_text = message.answer.await_args_list[-1].args[0]
    assert "❌" in final_text
    assert "SFL_AUTH_TOKEN" in final_text
