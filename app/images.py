from asyncpg import Pool

SITE_IMAGE_BASE_URL = "https://goblincodex.fun/sprites/"

DEFAULT_IMAGES = {
    "wearable": f"{SITE_IMAGE_BASE_URL}wearables/255.webp",
    "collectible": f"{SITE_IMAGE_BASE_URL}sfts/alba.webp",
    "nft": f"{SITE_IMAGE_BASE_URL}sfts/alba.webp",
    "fallback": f"{SITE_IMAGE_BASE_URL}sfts/alba.webp",
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
