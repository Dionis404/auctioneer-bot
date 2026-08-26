import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from asyncpg import Pool

from app.config import Config
from app.images import get_item_image
from app.jobs.auctions import schedule_all_pending
from app.jobs.notifications import (
    DIVIDER,
    format_bid,
    format_msk_time,
    send_admin_alert,
    send_with_image_preview,
)
from app.sfl_client import AuthExpiredError
from app.sync import sync_auctions, sync_results

logger = logging.getLogger(__name__)

router = Router(name="commands")

JOB_PREFIXES = ("reminder_", "started_", "delete_")

TEST_NOTIFICATION_TYPES = ("reminder", "started")

# Community API rate limit is ~1 request/5s per IP; space out sequential
# per-auction requests in /backfill_results to avoid immediately hitting it.
BACKFILL_REQUEST_DELAY_SECONDS = 5


def _is_admin(message: Message, config: Config) -> bool:
    return message.from_user is not None and message.from_user.id in config.admin_ids


def get_scheduler_summary(scheduler: AsyncIOScheduler) -> dict:
    jobs = scheduler.get_jobs()

    counts = {prefix: 0 for prefix in JOB_PREFIXES}
    for job in jobs:
        for prefix in JOB_PREFIXES:
            if job.id.startswith(prefix):
                counts[prefix] += 1
                break

    next_run = min(
        (job.next_run_time for job in jobs if job.next_run_time is not None),
        default=None,
    )

    return {"total": len(jobs), "counts": counts, "next_run": next_run}


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    await message.answer("pong")


@router.message(Command("status"))
async def cmd_status(message: Message, scheduler: AsyncIOScheduler, config: Config) -> None:
    if not _is_admin(message, config):
        return

    summary = get_scheduler_summary(scheduler)

    lines = [f"Всего job'ов: {summary['total']}"]
    for prefix in JOB_PREFIXES:
        lines.append(f"  {prefix}*: {summary['counts'][prefix]}")
    next_run = summary["next_run"]
    lines.append(
        f"Ближайший запуск: {next_run.isoformat() if next_run else 'нет запланированных'}"
    )

    await message.answer("\n".join(lines))


@router.message(Command("update_auctions"))
async def cmd_update_auctions(
    message: Message,
    bot: Bot,
    db_pool: Pool,
    scheduler: AsyncIOScheduler,
    config: Config,
) -> None:
    if not _is_admin(message, config):
        return

    await message.answer("🔄 Обновляю список аукционов...")

    try:
        affected = await sync_auctions(db_pool, config.sfl_api_key)
    except AuthExpiredError:
        await message.answer(
            "❌ Ключ SFL_API_KEY отклонён (401) — нужно проверить/обновить SFL_API_KEY."
        )
        await send_admin_alert(
            bot,
            config.admin_ids,
            "❌ Ключ SFL_API_KEY отклонён (401) — нужно проверить/обновить SFL_API_KEY.",
        )
        return

    await schedule_all_pending(bot, db_pool, scheduler, config)

    summary = get_scheduler_summary(scheduler)
    await message.answer(
        "✅ Обновление завершено.\n"
        f"Обработано аукционов: {affected}\n"
        f"Всего job'ов в шедулере: {summary['total']}"
    )


@router.message(Command("backfill_results"))
async def cmd_backfill_results(
    message: Message,
    bot: Bot,
    db_pool: Pool,
    config: Config,
) -> None:
    if not _is_admin(message, config):
        return

    rows = await db_pool.fetch(
        """
        SELECT a.auction_id
        FROM auctions a
        LEFT JOIN auction_results r ON r.auction_id = a.auction_id
        WHERE a.end_at < now()
          AND (
              a.results_fetched = false
              OR r.participant_count IS NULL
              OR r.leaderboard IS NULL
          )
        """
    )

    if not rows:
        await message.answer("Нет завершённых аукционов без результатов.")
        return

    await message.answer(
        f"⚙️ Догружаю результаты для {len(rows)} завершённых аукционов..."
    )

    fetched = 0
    not_ready = 0

    for index, row in enumerate(rows):
        if index > 0:
            await asyncio.sleep(BACKFILL_REQUEST_DELAY_SECONDS)

        try:
            success = await sync_results(db_pool, row["auction_id"], config.sfl_api_key)
        except AuthExpiredError:
            await send_admin_alert(
                bot,
                config.admin_ids,
                "❌ Ключ SFL_API_KEY отклонён (401) — нужно проверить/обновить SFL_API_KEY.",
            )
            return

        if success:
            fetched += 1
        else:
            not_ready += 1

    lines = ["✅ Готово.", f"Успешно достано: {fetched}"]
    if not_ready:
        lines.append(f"Аукцион ещё не завершён/не готов (попробуйте позже): {not_ready}")

    await message.answer("\n".join(lines))


@router.message(Command("next_auction"))
async def cmd_next_auction(
    message: Message,
    bot: Bot,
    db_pool: Pool,
    config: Config,
) -> None:
    if not _is_admin(message, config):
        return

    row = await db_pool.fetchrow(
        """
        SELECT item_name, item_type, supply, sfl_price, ingredients, start_at
        FROM auctions
        WHERE start_at > now()
        ORDER BY start_at ASC
        LIMIT 1
        """
    )
    if row is None:
        await message.answer("Нет запланированных аукционов.")
        return

    item_name = row["item_name"]
    item_type = row["item_type"]

    caption = (
        "Ближайший аукцион\n\n"
        "⏰ <b>{item_name}</b> ({item_type})\n"
        "{divider}\n"
        "💰 {bid}\n"
        "🎟 Лотов: {supply}\n\n"
        "🕑 Начало: {start_at}"
    ).format(
        item_name=item_name,
        item_type=item_type,
        divider=DIVIDER,
        bid=format_bid(row["sfl_price"], row["ingredients"]),
        supply=row["supply"],
        start_at=format_msk_time(row["start_at"]),
    )

    image_url = await get_item_image(db_pool, item_name, item_type)
    chat_id = message.chat.id

    try:
        await send_with_image_preview(bot, chat_id, caption, image_url, item_name)
    except Exception:
        logger.exception("next_auction: failed to send preview, falling back to text")
        await bot.send_message(chat_id, caption)


@router.message(Command("test_notification"))
async def cmd_test_notification(
    message: Message,
    command: CommandObject,
    bot: Bot,
    db_pool: Pool,
    config: Config,
) -> None:
    if not _is_admin(message, config):
        return

    notification_type = (command.args or "reminder").strip().lower()

    if notification_type not in TEST_NOTIFICATION_TYPES:
        await message.answer(
            "Неизвестный тип уведомления. Доступные варианты: "
            + ", ".join(TEST_NOTIFICATION_TYPES)
        )
        return

    if config.notify_chat_id is None:
        await message.answer("NOTIFY_CHAT_ID не настроен.")
        return

    row = await db_pool.fetchrow(
        """
        SELECT item_name, item_type FROM auctions
        WHERE item_name IS NOT NULL
        ORDER BY start_at ASC NULLS LAST
        LIMIT 1
        """
    )
    if row is None:
        await message.answer("В таблице auctions нет ни одной записи для теста.")
        return

    item_name = row["item_name"]
    item_type = row["item_type"]
    image_url = await get_item_image(db_pool, item_name, item_type)

    if notification_type == "reminder":
        start_at = datetime.now(timezone.utc) + timedelta(hours=1)
        caption = (
            f"⏰ <b>{item_name}</b> ({item_type})\n"
            f"{DIVIDER}\n"
            f"Через час старт аукциона!\n\n"
            f"💰 {format_bid(1, None)}\n"
            f"🎟 Лотов: 50\n\n"
            f"🕑 Начало: {format_msk_time(start_at)}"
        )
    else:
        caption = (
            f"🔨 <b>{item_name}</b>\n"
            f"{DIVIDER}\n"
            f"Аукцион стартовал! Успей сделать ставку."
        )

    try:
        await send_with_image_preview(
            bot, config.notify_chat_id, caption, image_url, item_name
        )
    except Exception:
        logger.exception("test_notification: failed to send preview, falling back to text")
        await bot.send_message(config.notify_chat_id, caption)

    await message.answer(f"Тестовое уведомление '{notification_type}' отправлено.")
