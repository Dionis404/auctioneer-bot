from unittest.mock import AsyncMock, MagicMock

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Config
from app.handlers import commands as commands_module
from app.handlers.commands import cmd_update_auctions
from app.sfl_client import AuthExpiredError


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


def _make_message(user_id: int = 42) -> MagicMock:
    message = MagicMock()
    message.from_user.id = user_id
    message.answer = AsyncMock()
    return message


async def test_rejects_non_admin():
    message = _make_message(user_id=1)
    bot = AsyncMock()
    pool = object()
    scheduler = AsyncIOScheduler()
    config = _make_config()

    await cmd_update_auctions(message, bot, pool, scheduler, config)

    message.answer.assert_not_called()


async def test_reports_progress_and_summary(monkeypatch):
    message = _make_message()
    bot = AsyncMock()
    pool = object()
    scheduler = AsyncIOScheduler()
    config = _make_config()

    sync_auctions_mock = AsyncMock(return_value=1111)
    monkeypatch.setattr(commands_module, "sync_auctions", sync_auctions_mock)
    schedule_mock = AsyncMock()
    monkeypatch.setattr(commands_module, "schedule_all_pending", schedule_mock)
    monkeypatch.setattr(
        commands_module,
        "get_scheduler_summary",
        lambda s: {"total": 726, "counts": {}, "next_run": None},
    )

    await cmd_update_auctions(message, bot, pool, scheduler, config)

    sync_auctions_mock.assert_awaited_once_with(pool, "key")
    schedule_mock.assert_awaited_once_with(bot, pool, scheduler, config)

    assert message.answer.await_count == 2
    first_call_text = message.answer.await_args_list[0].args[0]
    final_text = message.answer.await_args_list[1].args[0]
    assert "🔄" in first_call_text
    assert "✅ Обновление завершено." in final_text
    assert "Обработано аукционов: 1111" in final_text
    assert "Всего job'ов в шедулере: 726" in final_text


async def test_handles_auth_expired(monkeypatch):
    message = _make_message()
    bot = AsyncMock()
    pool = object()
    scheduler = AsyncIOScheduler()
    config = _make_config()

    monkeypatch.setattr(
        commands_module, "sync_auctions", AsyncMock(side_effect=AuthExpiredError("rejected"))
    )
    schedule_mock = AsyncMock()
    monkeypatch.setattr(commands_module, "schedule_all_pending", schedule_mock)
    send_alert_mock = AsyncMock()
    monkeypatch.setattr(commands_module, "send_admin_alert", send_alert_mock)

    await cmd_update_auctions(message, bot, pool, scheduler, config)

    schedule_mock.assert_not_called()
    send_alert_mock.assert_awaited_once()

    final_text = message.answer.await_args_list[-1].args[0]
    assert "❌" in final_text
    assert "SFL_API_KEY" in final_text
