import pytest
from PIL import Image

from app.image_compose import (
    ASSETS_DIR,
    BACKGROUND_FILES,
    LOCAL_SPRITE_PREFIX,
    SAFE_BOX,
    _download_sprite,
    _fit_sprite,
    _load_backgrounds,
    compose,
    pick_background_index,
    render_item_on_background,
)


def test_background_files_exist():
    for path in BACKGROUND_FILES:
        assert path.exists(), f"missing background file: {path}"


def test_fallback_sprite_file_exists():
    assert (ASSETS_DIR / "fallback.png").exists()


@pytest.mark.asyncio
async def test_download_sprite_loads_local_file_for_local_prefix():
    sprite = await _download_sprite(f"{LOCAL_SPRITE_PREFIX}fallback.png")
    assert sprite.mode == "RGBA"


@pytest.mark.asyncio
async def test_render_item_on_background_works_with_local_sprite():
    png_bytes = await render_item_on_background(
        f"{LOCAL_SPRITE_PREFIX}fallback.png", "auction-1"
    )
    assert isinstance(png_bytes, bytes)
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_backgrounds_load_as_rgba_512_tall():
    backgrounds = _load_backgrounds()
    assert len(backgrounds) == 4
    for bg in backgrounds:
        assert bg.mode == "RGBA"
        assert bg.height == 512


def test_pick_background_index_is_deterministic_per_auction_id():
    idx1 = pick_background_index("auction-abc")
    idx2 = pick_background_index("auction-abc")
    assert idx1 == idx2
    assert 0 <= idx1 < 4


def test_pick_background_index_in_range_for_various_ids():
    for auction_id in ["a", "salt-rug-2026-08-17-drop-2", "", "🎉"]:
        idx = pick_background_index(auction_id)
        assert 0 <= idx < 4


def test_fit_sprite_preserves_aspect_ratio_and_fits_in_box():
    sprite = Image.new("RGBA", (100, 50), (255, 0, 0, 255))
    fitted = _fit_sprite(sprite, SAFE_BOX)

    box_w = SAFE_BOX[2] - SAFE_BOX[0]
    box_h = SAFE_BOX[3] - SAFE_BOX[1]
    assert fitted.width <= box_w
    assert fitted.height <= box_h
    # aspect ratio (2:1) preserved
    assert abs(fitted.width / fitted.height - 2.0) < 0.05


def test_fit_sprite_upscales_small_sprite_to_fill_box():
    sprite = Image.new("RGBA", (16, 16), (0, 255, 0, 255))
    fitted = _fit_sprite(sprite, SAFE_BOX)

    box_w = SAFE_BOX[2] - SAFE_BOX[0]
    box_h = SAFE_BOX[3] - SAFE_BOX[1]
    # square sprite should scale up to touch the shorter box dimension
    assert min(fitted.width, fitted.height) == min(box_w, box_h)


def test_compose_returns_valid_png_bytes_matching_background_size():
    background = _load_backgrounds()[0]
    sprite = Image.new("RGBA", (32, 32), (10, 20, 30, 255))

    png_bytes = compose(background, sprite)

    assert isinstance(png_bytes, bytes)
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    import io

    result = Image.open(io.BytesIO(png_bytes))
    assert result.size == background.size


def test_compose_centers_sprite_within_safe_box():
    background = _load_backgrounds()[0]
    sprite = Image.new("RGBA", (40, 40), (255, 255, 255, 255))

    png_bytes = compose(background, sprite)

    import io

    result = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    box_cx = (SAFE_BOX[0] + SAFE_BOX[2]) // 2
    box_cy = (SAFE_BOX[1] + SAFE_BOX[3]) // 2

    # the exact center pixel should now be the opaque white sprite, not the
    # background's beige panel
    r, g, b, a = result.getpixel((box_cx, box_cy))
    assert (r, g, b) == (255, 255, 255)
    assert a == 255
