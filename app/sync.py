import logging

import asyncpg

from app.sfl_client import fetch_auction_results

logger = logging.getLogger(__name__)


async def sync_results(pool: asyncpg.Pool, auction_id: str, api_key: str | None = None) -> bool:
    result = await fetch_auction_results(auction_id, api_key)
    if result is None:
        return False

    status = result.get("status")
    if status != "complete":
        logger.debug(
            "sync_results: auction not complete yet: auction_id=%s status=%s",
            auction_id,
            status,
        )
        return False

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO auction_results (
                    auction_id, my_status, participant_count, supply,
                    leaderboard, fetched_at
                )
                VALUES ($1, $2, $3, $4, $5, now())
                ON CONFLICT (auction_id) DO UPDATE SET
                    my_status         = EXCLUDED.my_status,
                    participant_count = EXCLUDED.participant_count,
                    supply            = EXCLUDED.supply,
                    leaderboard       = EXCLUDED.leaderboard,
                    fetched_at        = now()
                """,
                auction_id,
                status,
                result.get("participantCount"),
                result.get("supply"),
                result.get("leaderboard"),
            )

            await conn.execute(
                "UPDATE auctions SET results_fetched = true WHERE auction_id = $1",
                auction_id,
            )

    return True
