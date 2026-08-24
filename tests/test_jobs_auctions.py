from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Config
from app.jobs import auctions as jobs_auctions


def _make_config(**overrides) -> Config:
    base = dict(
        telegram_bot_token="t",
        database_url="postgresql://x",
        alert_chat_id=999,
        notify_chat_id=None,
        admin_ids=[],
    )
    base.update(overrides)
    return Config(**base)


class FakePool:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, query, *args):
        return self._rows


@pytest.fixture
def scheduler():
    sched = AsyncIOScheduler()
    sched.start(paused=True)
    yield sched


async def test_schedule_all_pending_creates_deterministic_jobs(scheduler):
    now = datetime.now(timezone.utc)
    auction_id = "auction-future"
    start_at = now + timedelta(hours=2)
    end_at = now + timedelta(hours=3)

    pool = FakePool([{"auction_id": auction_id, "start_at": start_at, "end_at": end_at}])
    bot = AsyncMock()
    config = _make_config()

    await jobs_auctions.schedule_all_pending(bot, pool, scheduler, config)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        f"reminder_{auction_id}",
        f"delete_reminder_{auction_id}",
        f"started_{auction_id}",
        f"delete_started_{auction_id}",
    }

    # Calling again must not create duplicate jobs (replace_existing=True, same ids)
    await jobs_auctions.schedule_all_pending(bot, pool, scheduler, config)
    assert len(scheduler.get_jobs()) == 4


async def test_schedule_all_pending_skips_past_due_moments(scheduler):
    now = datetime.now(timezone.utc)
    auction_id = "auction-soon"
    # start_at is only 10 minutes away: reminder (-1h) and delete_reminder (-45m) are in the past
    start_at = now + timedelta(minutes=10)
    end_at = now + timedelta(hours=1)

    pool = FakePool([{"auction_id": auction_id, "start_at": start_at, "end_at": end_at}])
    bot = AsyncMock()
    config = _make_config()

    await jobs_auctions.schedule_all_pending(bot, pool, scheduler, config)

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        f"started_{auction_id}",
        f"delete_started_{auction_id}",
    }
