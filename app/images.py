from asyncpg import Pool

SITE_IMAGE_BASE_URL = "https://goblincodex.fun/sprites/"

# "local:" marks a sprite bundled with the bot (app/assets/) instead of one
# fetched from SITE_IMAGE_BASE_URL — used when no matching sprite exists on
# the site (e.g. generic NFT/Pet auctions, which have no concrete artwork
# before the item is revealed).
LOCAL_FALLBACK_SPRITE = "local:fallback.png"

DEFAULT_IMAGES = {
    "wearable": LOCAL_FALLBACK_SPRITE,
    "collectible": LOCAL_FALLBACK_SPRITE,
    "nft": LOCAL_FALLBACK_SPRITE,
    "fallback": LOCAL_FALLBACK_SPRITE,
}


async def get_item_image(pool: Pool, item_name: str, item_type: str) -> str:
    row = await pool.fetchrow(
        "SELECT sprite FROM sfl_items WHERE id = $1 AND type = $2",
        item_name,
        item_type,
    )
    if row and row["sprite"]:
        return f"{SITE_IMAGE_BASE_URL}{row['sprite']}"
    return DEFAULT_IMAGES.get(item_type, DEFAULT_IMAGES["fallback"])
