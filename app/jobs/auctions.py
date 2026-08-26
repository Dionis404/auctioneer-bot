import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from asyncpg import Pool

from app.config import Config
from app.jobs.notifications import (
    delete_notification,
    send_admin_alert,
    send_reminder,
    send_results_notification,
    send_started,
)
from app.sfl_client import AuthExpiredError
from app.sync import sync_results

logger = logging.getLogger(__name__)

# Community API rate limit is ~1 request/5s per IP (doubling to 10s if hammered),
# so retries stay just above that floor instead of the old conservative backoff.
RESULTS_RETRY_DELAYS_SECONDS = [5, 10, 15, 30]


async def schedule_all_pending(
    bot: Bot, pool: Pool, scheduler: AsyncIOScheduler, config: Config
) -> None:
    logger.info("schedule_all_pending: called")

    now = datetime.now(timezone.utc)

    rows = await pool.fetch(
        "SELECT auction_id, start_at, end_at FROM auctions WHERE start_at > now()"
    )

    logger.info(f"schedule_all_pending: found {len(rows)} future auctions")

    scheduled_count = 0

    for row in rows:
        auction_id = row["auction_id"]
        start_at: datetime = row["start_at"]
        end_at: datetime = row["end_at"]

        if _add_job_if_future(
            scheduler,
            job_id=f"reminder_{auction_id}",
            run_date=start_at - timedelta(hours=1),
            now=now,
            func=send_reminder,
            args=(bot, pool, auction_id),
        ):
            scheduled_count += 1

        if _add_job_if_future(
            scheduler,
            job_id=f"delete_reminder_{auction_id}",
            run_date=start_at - timedelta(minutes=45),
            now=now,
            func=delete_notification,
            args=(bot, pool, auction_id, "reminder_1h"),
        ):
            scheduled_count += 1

        if _add_job_if_future(
            scheduler,
            job_id=f"started_{auction_id}",
            run_date=start_at,
            now=now,
            func=send_started,
            args=(bot, pool, auction_id),
        ):
            scheduled_count += 1

        if end_at is not None:
            if _add_job_if_future(
                scheduler,
                job_id=f"delete_started_{auction_id}",
                run_date=end_at,
                now=now,
                func=delete_notification,
                args=(bot, pool, auction_id, "started"),
            ):
                scheduled_count += 1

            if _add_job_if_future(
                scheduler,
                job_id=f"results_{auction_id}",
                run_date=end_at + timedelta(seconds=20),
                now=now,
                func=fetch_and_send_results,
                args=(bot, pool, auction_id, scheduler, config),
                kwargs={"attempt": 0},
            ):
                scheduled_count += 1

    logger.info(f"schedule_all_pending: scheduled {scheduled_count} jobs total")


def _add_job_if_future(
    scheduler: AsyncIOScheduler,
    job_id: str,
    run_date: datetime,
    now: datetime,
    func,
    args: tuple,
    kwargs: dict | None = None,
) -> bool:
    if run_date <= now:
        logger.debug("Skipping past-due job %s (run_date=%s)", job_id, run_date)
        return False

    scheduler.add_job(
        func,
        trigger="date",
        run_date=run_date,
        id=job_id,
        replace_existing=True,
        args=args,
        kwargs=dict(kwargs or {}),
    )
    return True


async def fetch_and_send_results(
    bot: Bot,
    pool: Pool,
    auction_id: str,
    scheduler: AsyncIOScheduler,
    config: Config,
    attempt: int = 0,
) -> None:
    try:
        success = await sync_results(pool, auction_id, config.sfl_api_key)
    except AuthExpiredError:
        await send_admin_alert(
            bot,
            config.admin_ids,
            "❌ Ключ SFL_API_KEY отклонён (401) — нужно проверить/обновить SFL_API_KEY.",
        )
        return

    if success:
        await send_results_notification(bot, pool, auction_id)
        return

    if attempt >= len(RESULTS_RETRY_DELAYS_SECONDS):
        logger.warning(
            "results not available after max retries: auction_id=%s", auction_id
        )
        return

    delay = RESULTS_RETRY_DELAYS_SECONDS[attempt]
    run_date = datetime.now(timezone.utc) + timedelta(seconds=delay)
    scheduler.add_job(
        fetch_and_send_results,
        trigger="date",
        run_date=run_date,
        id=f"results_{auction_id}_retry_{attempt + 1}",
        replace_existing=True,
        args=(bot, pool, auction_id, scheduler, config),
        kwargs={"attempt": attempt + 1},
    )
