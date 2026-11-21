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
    """fetch() отдаёт список аукционов, fetchval() — признак готовых результатов."""

    def __init__(self, rows, results_ready: bool = False):
        self._rows = rows
        self._results_ready = results_ready

    async def fetch(self, query, *args):
        return self._rows

    async def fetchval(self, query, *args):
        return 1 if self._results_ready else None


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
        f"results_{auction_id}",
    }

    # Calling again must not create duplicate jobs (replace_existing=True, same ids)
    await jobs_auctions.schedule_all_pending(bot, pool, scheduler, config)
    assert len(scheduler.get_jobs()) == 5


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
        f"results_{auction_id}",
    }


async def test_wait_and_send_results_reschedules_when_not_ready(scheduler, monkeypatch):
    bot = AsyncMock()
    pool = FakePool([], results_ready=False)
    config = _make_config()

    send_results_mock = AsyncMock()
    monkeypatch.setattr(jobs_auctions, "send_results_notification", send_results_mock)

    await jobs_auctions.wait_and_send_results(
        bot, pool, "auction-x", scheduler, config, attempt=0
    )

    send_results_mock.assert_not_called()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "results_auction-x_retry_1" in job_ids


async def test_wait_and_send_results_stops_after_max_retries(scheduler, monkeypatch):
    bot = AsyncMock()
    pool = FakePool([], results_ready=False)
    config = _make_config()

    send_results_mock = AsyncMock()
    monkeypatch.setattr(jobs_auctions, "send_results_notification", send_results_mock)

    max_attempt = len(jobs_auctions.RESULTS_RETRY_DELAYS_SECONDS)
    await jobs_auctions.wait_and_send_results(
        bot, pool, "auction-x", scheduler, config, attempt=max_attempt
    )

    send_results_mock.assert_not_called()
    assert scheduler.get_jobs() == []


async def test_wait_and_send_results_sends_notification_when_ready(scheduler, monkeypatch):
    bot = AsyncMock()
    pool = FakePool([], results_ready=True)
    config = _make_config()

    send_results_mock = AsyncMock()
    monkeypatch.setattr(jobs_auctions, "send_results_notification", send_results_mock)

    await jobs_auctions.wait_and_send_results(
        bot, pool, "auction-x", scheduler, config, attempt=0
    )

    send_results_mock.assert_awaited_once_with(bot, pool, "auction-x", config.routerai_api_key)
    assert scheduler.get_jobs() == []


async def test_refresh_auctions_job_rereads_db_and_schedules(scheduler, monkeypatch):
    bot = AsyncMock()
    pool = object()
    config = _make_config()

    schedule_mock = AsyncMock()
    monkeypatch.setattr(jobs_auctions, "schedule_all_pending", schedule_mock)

    await jobs_auctions.refresh_auctions_job(bot, pool, scheduler, config)

    schedule_mock.assert_awaited_once_with(bot, pool, scheduler, config)
