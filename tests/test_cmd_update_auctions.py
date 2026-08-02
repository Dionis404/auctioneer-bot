from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Config
from app.handlers import commands as commands_module
from app.handlers.commands import cmd_update_auctions
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


@pytest.fixture
def scheduler():
    sched = AsyncIOScheduler()
    sched.start(paused=True)
    yield sched


async def test_rejects_non_admin(scheduler, monkeypatch):
    message = _make_message(user_id=1)
    bot = AsyncMock()
    pool = object()
    config = _make_config()

    sync_mock = AsyncMock()
    monkeypatch.setattr(commands_module, "sync_auctions", sync_mock)

    await cmd_update_auctions(message, bot, pool, scheduler, config)

    sync_mock.assert_not_called()
    message.answer.assert_not_called()


async def test_reports_progress_and_summary(scheduler, monkeypatch):
    message = _make_message()
    bot = AsyncMock()
    pool = object()
    config = _make_config()

    sync_mock = AsyncMock(return_value=1111)
    monkeypatch.setattr(commands_module, "sync_auctions", sync_mock)
    schedule_mock = AsyncMock()
    monkeypatch.setattr(commands_module, "schedule_all_pending", schedule_mock)
    monkeypatch.setattr(
        commands_module,
        "get_scheduler_summary",
        lambda s: {"total": 726, "counts": {}, "next_run": None},
    )

    await cmd_update_auctions(message, bot, pool, scheduler, config)

    sync_mock.assert_awaited_once_with(pool, "token")
    schedule_mock.assert_awaited_once_with(bot, pool, scheduler, config)

    assert message.answer.await_count == 2
    first_call_text = message.answer.await_args_list[0].args[0]
    final_text = message.answer.await_args_list[1].args[0]
    assert "🔄" in first_call_text
    assert "✅ Обновление завершено." in final_text
    assert "Обработано аукционов: 1111" in final_text
    assert "Всего job'ов в шедулере: 726" in final_text


async def test_handles_auth_expired(scheduler, monkeypatch):
    message = _make_message()
    bot = AsyncMock()
    pool = object()
    config = _make_config()

    async def _raise(*args, **kwargs):
        raise AuthExpiredError("expired")

    monkeypatch.setattr(commands_module, "sync_auctions", _raise)
    schedule_mock = AsyncMock()
    monkeypatch.setattr(commands_module, "schedule_all_pending", schedule_mock)
    send_alert_mock = AsyncMock()
    monkeypatch.setattr(commands_module, "send_alert", send_alert_mock)

    await cmd_update_auctions(message, bot, pool, scheduler, config)

    schedule_mock.assert_not_called()
    send_alert_mock.assert_awaited_once()

    final_text = message.answer.await_args_list[-1].args[0]
    assert "❌" in final_text
    assert "SFL_AUTH_TOKEN" in final_text


def test_get_scheduler_summary_counts_by_prefix(scheduler):
    from app.handlers.commands import get_scheduler_summary

    def _noop():
        pass

    scheduler.add_job(_noop, trigger="interval", seconds=60, id="reminder_a")
    scheduler.add_job(_noop, trigger="interval", seconds=60, id="reminder_b")
    scheduler.add_job(_noop, trigger="interval", seconds=60, id="started_a")
    scheduler.add_job(_noop, trigger="interval", seconds=60, id="delete_reminder_a")

    summary = get_scheduler_summary(scheduler)

    assert summary["total"] == 4
    assert summary["counts"]["reminder_"] == 2
    assert summary["counts"]["started_"] == 1
    assert summary["counts"]["delete_"] == 1
    assert summary["next_run"] is not None
