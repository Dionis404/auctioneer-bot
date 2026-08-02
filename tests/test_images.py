from app.images import DEFAULT_IMAGES, SITE_IMAGE_BASE_URL, get_item_image


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
