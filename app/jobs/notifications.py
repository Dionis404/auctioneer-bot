import json
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, Message
from asyncpg import Pool

from app.image_compose import render_item_on_background
from app.images import get_item_image
from app.llm_flavor import generate_flavor_line

logger = logging.getLogger(__name__)

MSK_TZ = ZoneInfo("Europe/Moscow")

CAPTION_LIMIT = 1024

DIVIDER = "─" * 16


async def send_with_image_preview(
    bot: Bot, chat_id: int, text: str, image_url: str, background_key: str
) -> Message:
    photo: str | BufferedInputFile = image_url
    try:
        composed = await render_item_on_background(image_url, background_key)
        photo = BufferedInputFile(composed, filename="auction.png")
    except Exception:
        logger.exception(
            "send_with_image_preview: failed to compose background, falling back to raw sprite URL"
        )

    if len(text) <= CAPTION_LIMIT:
        return await bot.send_photo(
            chat_id,
            photo=photo,
            caption=text,
            show_caption_above_media=True,
        )

    await bot.send_message(chat_id, text)
    return await bot.send_photo(chat_id, photo=photo)


def _notify_chat_id() -> int | None:
    raw = os.getenv("NOTIFY_CHAT_ID")
    return int(raw) if raw else None


def format_msk_time(dt: datetime) -> str:
    return dt.astimezone(MSK_TZ).strftime("%d.%m %H:%M МСК")


def _coerce_jsonb(value):
    """Legacy rows may hold a double-encoded JSON string; parse it back into a dict/list."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None
    return value


def format_bid(sfl_price, ingredients) -> str:
    ingredients = _coerce_jsonb(ingredients)
    if sfl_price:
        return "Ставка: Flower"
    if ingredients:
        names = [name for name, enabled in ingredients.items() if enabled]
        if names:
            return "Ставка: " + ", ".join(names)
    return "Ставка: —"


def _entry_bid(entry: dict) -> str:
    sfl = entry.get("sfl")
    if sfl:
        return f"{sfl} Flower"
    items = entry.get("items")
    if items:
        name, amount = next(iter(items.items()))
        return f"{amount} {name}"
    return "—"


def format_top_and_last(leaderboard: list[dict]) -> str:
    leaderboard = _coerce_jsonb(leaderboard)

    entries = sorted(
        (entry for entry in (leaderboard or []) if entry.get("rank") is not None),
        key=lambda entry: entry["rank"],
    )

    lines = [
        f"{entry['rank']}. {entry.get('username') or 'без ника'} — {_entry_bid(entry)}"
        for entry in entries
    ]
    return "\n".join(lines) if lines else "нет данных"


async def _with_flavor(text: str, api_key: str | None, context: str) -> str:
    line = await generate_flavor_line(api_key, context)
    if not line:
        return text
    return f"{text}\n\n<i>{line}</i>"


async def send_reminder(
    bot: Bot, pool: Pool, auction_id: str, routerai_api_key: str | None = None
) -> None:
    notify_chat_id = _notify_chat_id()
    if notify_chat_id is None:
        logger.warning(
            "NOTIFY_CHAT_ID is not configured, dropping reminder for auction_id=%s",
            auction_id,
        )
        return

    row = await pool.fetchrow(
        """
        SELECT item_name, item_type, supply, sfl_price, ingredients, start_at
        FROM auctions WHERE auction_id = $1
        """,
        auction_id,
    )
    if row is None:
        logger.warning("send_reminder: auction not found: %s", auction_id)
        return

    item_name = row["item_name"]
    item_type = row["item_type"]

    text = (
        f"⏰ <b>{item_name}</b> ({item_type})\n"
        f"{DIVIDER}\n"
        f"Через час старт аукциона!\n\n"
        f"💰 {format_bid(row['sfl_price'], row['ingredients'])}\n"
        f"🎟 Лотов: {row['supply']}\n\n"
        f"🕑 Начало: {format_msk_time(row['start_at'])}"
    )
    text = await _with_flavor(
        text, routerai_api_key, f"Через час стартует аукцион на {item_name}."
    )

    image_url = await get_item_image(pool, item_name, item_type)
    message = await send_with_image_preview(bot, notify_chat_id, text, image_url, auction_id)

    await pool.execute(
        """
        INSERT INTO auction_notifications (auction_id, kind, chat_id, message_id, delete_at)
        VALUES ($1, 'reminder_1h', $2, $3, $4::timestamptz - interval '45 minutes')
        """,
        auction_id,
        notify_chat_id,
        message.message_id,
        row["start_at"],
    )


async def send_started(
    bot: Bot, pool: Pool, auction_id: str, routerai_api_key: str | None = None
) -> None:
    notify_chat_id = _notify_chat_id()
    if notify_chat_id is None:
        logger.warning(
            "NOTIFY_CHAT_ID is not configured, dropping started notification for auction_id=%s",
            auction_id,
        )
        return

    row = await pool.fetchrow(
        "SELECT item_name, item_type, end_at FROM auctions WHERE auction_id = $1",
        auction_id,
    )
    if row is None:
        logger.warning("send_started: auction not found: %s", auction_id)
        return

    item_name = row["item_name"]
    item_type = row["item_type"]

    text = (
        f"🔨 <b>{item_name}</b>\n"
        f"{DIVIDER}\n"
        f"Аукцион стартовал! Успей сделать ставку."
    )
    text = await _with_flavor(
        text, routerai_api_key, f"Аукцион на {item_name} только что стартовал."
    )

    image_url = await get_item_image(pool, item_name, item_type)
    message = await send_with_image_preview(bot, notify_chat_id, text, image_url, auction_id)

    await pool.execute(
        """
        INSERT INTO auction_notifications (auction_id, kind, chat_id, message_id, delete_at)
        VALUES ($1, 'started', $2, $3, $4)
        """,
        auction_id,
        notify_chat_id,
        message.message_id,
        row["end_at"],
    )


async def send_results_notification(
    bot: Bot, pool: Pool, auction_id: str, routerai_api_key: str | None = None
) -> None:
    notify_chat_id = _notify_chat_id()
    if notify_chat_id is None:
        logger.warning(
            "NOTIFY_CHAT_ID is not configured, dropping results notification for auction_id=%s",
            auction_id,
        )
        return

    row = await pool.fetchrow(
        """
        SELECT a.item_name, a.item_type, r.participant_count, r.leaderboard
        FROM auction_results r
        JOIN auctions a ON a.auction_id = r.auction_id
        WHERE r.auction_id = $1
        """,
        auction_id,
    )
    if row is None:
        logger.warning("send_results_notification: results not found: %s", auction_id)
        return

    item_name = row["item_name"]
    item_type = row["item_type"]

    text = (
        f"🏁 <b>{item_name}</b>\n"
        f"{DIVIDER}\n"
        f"Аукцион завершён!\n\n"
        f"👥 Участников: {row['participant_count']}\n\n"
        f"🏆 Топ-3 и последнее место:\n{format_top_and_last(row['leaderboard'])}"
    )
    text = await _with_flavor(
        text, routerai_api_key, f"Аукцион на {item_name} завершился."
    )

    image_url = await get_item_image(pool, item_name, item_type)
    message = await send_with_image_preview(bot, notify_chat_id, text, image_url, auction_id)

    await pool.execute(
        """
        INSERT INTO auction_notifications (auction_id, kind, chat_id, message_id, delete_at)
        VALUES ($1, 'results', $2, $3, NULL)
        """,
        auction_id,
        notify_chat_id,
        message.message_id,
    )


async def send_admin_alert(bot: Bot, admin_ids: list[int], text: str) -> None:
    if not admin_ids:
        logger.warning("ADMIN_IDS is not configured, dropping alert: %s", text)
        return

    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("send_admin_alert: failed to message admin_id=%s", admin_id)


async def delete_notification(bot: Bot, pool: Pool, auction_id: str, kind: str) -> None:
    row = await pool.fetchrow(
        """
        SELECT message_id, chat_id FROM auction_notifications
        WHERE auction_id = $1 AND kind = $2 AND deleted = false
        """,
        auction_id,
        kind,
    )
    if row is None:
        return

    try:
        await bot.delete_message(row["chat_id"], row["message_id"])
    except TelegramBadRequest:
        logger.debug(
            "delete_notification: message already gone auction_id=%s kind=%s",
            auction_id,
            kind,
        )

    await pool.execute(
        """
        UPDATE auction_notifications SET deleted = true
        WHERE auction_id = $1 AND kind = $2
        """,
        auction_id,
        kind,
    )
