import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher, Router
from aiogram.types import Chat, Message, Update, User

from app.config import Config
from app.handlers import commands, fallback


@pytest.fixture(autouse=True)
def _detach_shared_routers():
    yield
    commands.router._parent_router = None
    fallback.router._parent_router = None


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


def _make_dispatcher(config: Config) -> Dispatcher:
    dp = Dispatcher()
    dp["config"] = config
    dp["db_pool"] = MagicMock()
    dp["scheduler"] = MagicMock(get_jobs=lambda: [])
    dp.include_router(commands.router)
    dp.include_router(fallback.router)
    return dp


def _make_update(
    text: str | None = None,
    user_id: int = 1,
    chat_id: int = 100,
    chat_type: str = "private",
    update_id: int = 1,
) -> Update:
    chat = Chat(id=chat_id, type=chat_type)
    user = User(id=user_id, is_bot=False, first_name="Test")
    message = Message(
        message_id=1, date=int(time.time()), chat=chat, from_user=user, text=text
    )
    return Update(update_id=update_id, message=message)


async def test_known_command_still_resolves_to_its_handler():
    config = _make_config()
    dp = _make_dispatcher(config)
    bot = AsyncMock()

    captured = {}
    orig_answer = Message.answer

    async def fake_answer(self, text, *args, **kwargs):
        captured["text"] = text

    Message.answer = fake_answer
    try:
        await dp.feed_update(bot, _make_update(text="/ping", user_id=1))
    finally:
        Message.answer = orig_answer

    assert captured["text"] == "pong"


async def test_unknown_command_admin_gets_full_list():
    config = _make_config()
    dp = _make_dispatcher(config)
    bot = AsyncMock()

    captured = {}

    async def fake_answer(self, text, *args, **kwargs):
        captured["text"] = text

    orig_answer = Message.answer
    Message.answer = fake_answer
    try:
        await dp.feed_update(bot, _make_update(text="/frobnicate", user_id=42))
    finally:
        Message.answer = orig_answer

    assert "Не знаю такую команду" in captured["text"]
    assert "/status" in captured["text"]
    assert "/next_auction" in captured["text"]
    assert "/test_notification" in captured["text"]


async def test_unknown_command_non_admin_gets_short_message():
    config = _make_config()
    dp = _make_dispatcher(config)
    bot = AsyncMock()

    captured = {}

    async def fake_answer(self, text, *args, **kwargs):
        captured["text"] = text

    orig_answer = Message.answer
    Message.answer = fake_answer
    try:
        await dp.feed_update(bot, _make_update(text="/frobnicate", user_id=999))
    finally:
        Message.answer = orig_answer

    assert captured["text"] == "Неизвестная команда"


async def test_plain_text_in_private_chat_gets_reply():
    config = _make_config()
    dp = _make_dispatcher(config)
    bot = AsyncMock()

    captured = {}

    async def fake_answer(self, text, *args, **kwargs):
        captured["text"] = text

    orig_answer = Message.answer
    Message.answer = fake_answer
    try:
        await dp.feed_update(
            bot, _make_update(text="hello", user_id=1, chat_type="private")
        )
    finally:
        Message.answer = orig_answer

    assert "Sunflower Land" in captured["text"]


async def test_plain_text_in_group_chat_gets_no_reply():
    config = _make_config()
    dp = _make_dispatcher(config)
    bot = AsyncMock()

    called = {"value": False}

    async def fake_answer(self, text, *args, **kwargs):
        called["value"] = True

    orig_answer = Message.answer
    Message.answer = fake_answer
    try:
        await dp.feed_update(
            bot, _make_update(text="hello group", user_id=1, chat_type="supergroup")
        )
    finally:
        Message.answer = orig_answer

    assert called["value"] is False


async def test_error_handler_prevents_feed_update_from_raising():
    dp = Dispatcher()
    boom_router = Router(name="boom")

    @boom_router.message()
    async def boom(message):
        raise RuntimeError("simulated crash")

    dp.include_router(boom_router)
    dp.errors.register(fallback.handle_error)

    bot = AsyncMock()
    bot.id = 111

    result = await dp.feed_update(bot, _make_update(text="trigger crash"))

    assert result is None
