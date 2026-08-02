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
    format_bid,
    format_msk_time,
    format_top_and_last,
    send_alert,
    send_with_image_preview,
)
from app.sfl_client import AuthExpiredError
from app.sync import sync_auctions, sync_results

logger = logging.getLogger(__name__)

router = Router(name="commands")

JOB_PREFIXES = ("reminder_", "started_", "results_", "delete_")

TEST_NOTIFICATION_TYPES = ("reminder", "started", "results")


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
        affected = await sync_auctions(db_pool, config.sfl_auth_token)
    except AuthExpiredError:
        await message.answer(
            "❌ Токен авторизации SFL истёк, нужно обновить SFL_AUTH_TOKEN"
        )
        await send_alert(
            bot,
            config.alert_chat_id,
            "SFL auth token expired, нужно обновить SFL_AUTH_TOKEN",
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
    db_pool: Pool,
    config: Config,
) -> None:
    if not _is_admin(message, config):
        return

    rows = await db_pool.fetch(
        """
        SELECT auction_id FROM auctions
        WHERE end_at < now() AND results_fetched = false
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

    for row in rows:
        try:
            success = await sync_results(
                db_pool, row["auction_id"], config.sfl_farm_id, config.sfl_auth_token
            )
        except AuthExpiredError:
            await message.answer(
                "❌ Токен авторизации SFL истёк, нужно обновить SFL_AUTH_TOKEN"
            )
            return

        if success:
            fetched += 1
        else:
            not_ready += 1

    lines = ["✅ Готово.", f"Успешно достано: {fetched}"]
    if not_ready:
        lines.append(f"API ещё не отдал (попробуйте позже): {not_ready}")

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

    if config.alert_chat_id is None:
        await message.answer("ALERT_CHAT_ID не настроен.")
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
        "⏰ Ближайший аукцион: <b>{item_name}</b> ({item_type})\n"
        "{bid}\n"
        "Лотов: {supply}\n"
        "Начало: {start_at}"
    ).format(
        item_name=item_name,
        item_type=item_type,
        bid=format_bid(row["sfl_price"], row["ingredients"]),
        supply=row["supply"],
        start_at=format_msk_time(row["start_at"]),
    )

    image_url = await get_item_image(db_pool, item_name, item_type)

    try:
        await send_with_image_preview(bot, config.alert_chat_id, caption, image_url)
    except Exception:
        logger.exception("next_auction: failed to send preview, falling back to text")
        await bot.send_message(config.alert_chat_id, caption)

    await message.answer("Информация о ближайшем аукционе отправлена.")


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
            "⏰ Аукцион начнётся через 1 час!\n\n"
            f"Предмет: <b>{item_name}</b> ({item_type})\n"
            f"{format_bid(1, None)}\n"
            f"Лотов: 50\n"
            f"Начало: {format_msk_time(start_at)}"
        )
    elif notification_type == "started":
        caption = (
            "🔨 Аукцион стартовал!\n\n"
            f"Предмет: <b>{item_name}</b> ({item_type})\n"
            f"{format_bid(1, None)}\n"
            f"Лотов: 50"
        )
    else:
        leaderboard = [
            {"rank": 1, "username": "test_user_1", "sfl": 0, "items": {"Gem": 9597}},
            {"rank": 2, "username": "test_user_2", "sfl": 0, "items": {"Gem": 9185}},
            {"rank": 3, "username": "test_user_3", "sfl": 0, "items": {"Gem": 8600}},
            {"rank": 50, "username": "test_user_4", "sfl": 0, "items": {"Gem": 6108}},
        ]
        caption = (
            "🏆 Результаты аукциона (тест)\n\n"
            f"Предмет: <b>{item_name}</b> ({item_type})\n"
            f"Участников: 275\n\n"
            f"Топ-3 и последнее место:\n{format_top_and_last(leaderboard)}"
        )

    try:
        await send_with_image_preview(bot, config.notify_chat_id, caption, image_url)
    except Exception:
        logger.exception("test_notification: failed to send preview, falling back to text")
        await bot.send_message(config.notify_chat_id, caption)

    await message.answer(f"Тестовое уведомление '{notification_type}' отправлено.")
