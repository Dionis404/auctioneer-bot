from unittest.mock import AsyncMock, MagicMock

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Config
from app.handlers import commands as commands_module
from app.handlers.commands import cmd_update_auctions


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


async def test_rejects_non_admin():
    message = _make_message(user_id=1)
    bot = AsyncMock()
    pool = object()
    scheduler = AsyncIOScheduler()
    config = _make_config()

    await cmd_update_auctions(message, bot, pool, scheduler, config)

    message.answer.assert_not_called()


async def test_rereads_schedule_from_db(monkeypatch):
    message = _make_message()
    bot = AsyncMock()
    pool = object()
    scheduler = AsyncIOScheduler()
    config = _make_config()

    schedule_mock = AsyncMock()
    monkeypatch.setattr(commands_module, "schedule_all_pending", schedule_mock)
    monkeypatch.setattr(
        commands_module,
        "get_scheduler_summary",
        lambda s: {"total": 726, "counts": {}, "next_run": None},
    )

    await cmd_update_auctions(message, bot, pool, scheduler, config)

    schedule_mock.assert_awaited_once_with(bot, pool, scheduler, config)

    assert message.answer.await_count == 2
    first_call_text = message.answer.await_args_list[0].args[0]
    final_text = message.answer.await_args_list[1].args[0]
    assert "🔄" in first_call_text
    assert "✅ Расписание перечитано." in final_text
    assert "Всего job'ов в шедулере: 726" in final_text
    assert "sfl-collector" in final_text
