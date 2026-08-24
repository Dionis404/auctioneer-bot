import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from asyncpg import Pool

from app.config import Config
from app.jobs.notifications import delete_notification, send_reminder, send_started

logger = logging.getLogger(__name__)


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
