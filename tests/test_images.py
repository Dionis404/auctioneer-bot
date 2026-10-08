from app.images import (
    DEFAULT_IMAGES,
    LOCAL_FALLBACK_SPRITE,
    SITE_IMAGE_BASE_URL,
    get_item_image,
)


class FakePool:
    def __init__(self, row):
        self._row = row

    async def fetchrow(self, query, *args):
        return self._row


async def test_get_item_image_uses_sprite_when_present():
    pool = FakePool({"sprite": "wearables/255.webp"})

    url = await get_item_image(pool, "Goblin Mask", "wearable")

    assert url == f"{SITE_IMAGE_BASE_URL}wearables/255.webp"


async def test_get_item_image_falls_back_when_no_row():
    pool = FakePool(None)

    url = await get_item_image(pool, "Unknown Pet Drop", "nft")

    assert url == DEFAULT_IMAGES["nft"]


async def test_get_item_image_falls_back_when_sprite_empty():
    pool = FakePool({"sprite": None})

    url = await get_item_image(pool, "Something", "collectible")

    assert url == DEFAULT_IMAGES["collectible"]


def test_all_default_images_use_local_fallback_sprite():
    assert all(value == LOCAL_FALLBACK_SPRITE for value in DEFAULT_IMAGES.values())


async def test_pet_nft_uses_egg_sprite_override_without_db_lookup():
    pool = FakePool(None)  # sfl_items has no "Pet"/nft row — override must win

    url = await get_item_image(pool, "Pet", "nft")

    assert url == f"{SITE_IMAGE_BASE_URL}icons/pet_egg.png"


async def test_override_does_not_apply_to_unrelated_nft():
    pool = FakePool(None)

    url = await get_item_image(pool, "Genie Lamp", "nft")

    assert url == DEFAULT_IMAGES["nft"]
