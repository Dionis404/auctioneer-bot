from asyncpg import Pool

SITE_IMAGE_BASE_URL = "https://goblincodex.fun/sprites/"

# "local:" marks a sprite bundled with the bot (app/assets/) instead of one
# fetched from SITE_IMAGE_BASE_URL — used when no matching sprite exists on
# the site and there's no better substitute.
LOCAL_FALLBACK_SPRITE = "local:fallback.png"

DEFAULT_IMAGES = {
    "wearable": LOCAL_FALLBACK_SPRITE,
    "collectible": LOCAL_FALLBACK_SPRITE,
    "nft": LOCAL_FALLBACK_SPRITE,
    "fallback": LOCAL_FALLBACK_SPRITE,
}

# Auctions where item_name/item_type don't match anything in sfl_items by
# name, but there IS a real, specific sprite for them under a different id —
# e.g. Pet auctions (item_name="Pet", item_type="nft") sell an unhatched egg,
# whose artwork is stored in sfl_items as id="Pet Egg", type="collectible".
# This is a genuine sprite, not a generic "nothing found" fallback.
KNOWN_ITEM_OVERRIDES = {
    ("Pet", "nft"): f"{SITE_IMAGE_BASE_URL}icons/pet_egg.png",
}


async def get_item_image(pool: Pool, item_name: str, item_type: str) -> str:
    override = KNOWN_ITEM_OVERRIDES.get((item_name, item_type))
    if override:
        return override

    row = await pool.fetchrow(
        "SELECT sprite FROM sfl_items WHERE id = $1 AND type = $2",
        item_name,
        item_type,
    )
    if row and row["sprite"]:
        return f"{SITE_IMAGE_BASE_URL}{row['sprite']}"
    return DEFAULT_IMAGES.get(item_type, DEFAULT_IMAGES["fallback"])
