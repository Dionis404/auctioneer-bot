import logging
from datetime import datetime, timezone

import asyncpg

from app.sfl_client import fetch_auction_results, fetch_auctions

logger = logging.getLogger(__name__)

_ITEM_NAME_FIELDS = ("wearable", "collectible", "nft")


def _ms_to_dt(ms: int | None) -> datetime | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _item_name(item: dict) -> str | None:
    for field in _ITEM_NAME_FIELDS:
        value = item.get(field)
        if value:
            return value
    return None


async def sync_auctions(pool: asyncpg.Pool, auth_token: str | None = None) -> int:
    data = await fetch_auctions(auth_token)
    auctions_block = data.get("auctions", {})
    items = auctions_block.get("auctions", [])
    total_supply = auctions_block.get("totalSupply", {})

    affected = 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            for item in items:
                result = await conn.execute(
                    """
                    INSERT INTO auctions (
                        auction_id, item_name, item_type, supply, sfl_price,
                        ingredients, start_at, end_at, chapter_limit, start_id,
                        raw, updated_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now()
                    )
                    ON CONFLICT (auction_id) DO UPDATE SET
                        item_name     = EXCLUDED.item_name,
                        item_type     = EXCLUDED.item_type,
                        supply        = EXCLUDED.supply,
                        sfl_price     = EXCLUDED.sfl_price,
                        ingredients   = EXCLUDED.ingredients,
                        start_at      = EXCLUDED.start_at,
                        end_at        = EXCLUDED.end_at,
                        chapter_limit = EXCLUDED.chapter_limit,
                        start_id      = EXCLUDED.start_id,
                        raw           = EXCLUDED.raw,
                        updated_at    = now()
                    """,
                    item.get("auctionId"),
                    _item_name(item),
                    item.get("type"),
                    item.get("supply"),
                    item.get("sfl"),
                    item.get("ingredients"),
                    _ms_to_dt(item.get("startAt")),
                    _ms_to_dt(item.get("endAt")),
                    item.get("chapterLimit"),
                    item.get("startId"),
                    item,
                )
                affected += int(result.split()[-1])

            for item_name, supply in total_supply.items():
                await conn.execute(
                    """
                    INSERT INTO item_total_supply (item_name, total_supply, updated_at)
                    VALUES ($1, $2, now())
                    ON CONFLICT (item_name) DO UPDATE SET
                        total_supply = EXCLUDED.total_supply,
                        updated_at   = now()
                    """,
                    item_name,
                    supply,
                )

    return affected


async def sync_results(pool: asyncpg.Pool, auction_id: str, farm_id: str, auth_token: str | None = None) -> bool:
    result = await fetch_auction_results(auction_id, farm_id, auth_token)
    if result is None:
        return False

    if result.get("participantCount") is None or result.get("leaderboard") is None:
        logger.debug(
            "sync_results: got 200 but results not ready yet: auction_id=%s",
            auction_id,
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
                result.get("status"),
                result.get("participantCount"),
                result.get("supply"),
                result.get("leaderboard"),
            )

            await conn.execute(
                "UPDATE auctions SET results_fetched = true WHERE auction_id = $1",
                auction_id,
            )

    return True
