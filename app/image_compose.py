import io
import logging
from pathlib import Path

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

BACKGROUNDS_DIR = Path(__file__).resolve().parent / "assets" / "backgrounds"
BACKGROUND_FILES = [
    BACKGROUNDS_DIR / "bg_1.png",
    BACKGROUNDS_DIR / "bg_2.png",
    BACKGROUNDS_DIR / "bg_3.png",
    BACKGROUNDS_DIR / "bg_4.png",
]

# Safe inner area shared by all four backgrounds (beige panel, clear of frame
# decorations), with a small inward margin so the sprite never touches it.
_SAFE_BOX_RAW = (73, 123, 613, 428)
_SAFE_MARGIN = 20
SAFE_BOX = (
    _SAFE_BOX_RAW[0] + _SAFE_MARGIN,
    _SAFE_BOX_RAW[1] + _SAFE_MARGIN,
    _SAFE_BOX_RAW[2] - _SAFE_MARGIN,
    _SAFE_BOX_RAW[3] - _SAFE_MARGIN,
)

_DOWNLOAD_TIMEOUT = 10.0

_backgrounds_cache: list[Image.Image] | None = None
_client: httpx.AsyncClient | None = None


def _load_backgrounds() -> list[Image.Image]:
    global _backgrounds_cache
    if _backgrounds_cache is None:
        _backgrounds_cache = [
            Image.open(path).convert("RGBA") for path in BACKGROUND_FILES
        ]
    return _backgrounds_cache


def init_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _get_client() -> httpx.AsyncClient:
    return _client if _client is not None else init_client()


def pick_background_index(auction_id: str) -> int:
    return hash(auction_id) % len(BACKGROUND_FILES)


async def _download_sprite(image_url: str) -> Image.Image:
    client = _get_client()
    response = await client.get(image_url)
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGBA")


def _fit_sprite(sprite: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    box_w = box[2] - box[0]
    box_h = box[3] - box[1]

    scale = min(box_w / sprite.width, box_h / sprite.height)
    new_size = (max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale)))
    return sprite.resize(new_size, Image.NEAREST)


def compose(background: Image.Image, sprite: Image.Image) -> bytes:
    canvas = background.copy()
    fitted = _fit_sprite(sprite, SAFE_BOX)

    box_cx = (SAFE_BOX[0] + SAFE_BOX[2]) // 2
    box_cy = (SAFE_BOX[1] + SAFE_BOX[3]) // 2
    paste_x = box_cx - fitted.width // 2
    paste_y = box_cy - fitted.height // 2

    canvas.alpha_composite(fitted, (paste_x, paste_y))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


async def render_item_on_background(image_url: str, auction_id: str) -> bytes:
    sprite = await _download_sprite(image_url)
    backgrounds = _load_backgrounds()
    background = backgrounds[pick_background_index(auction_id)]
    return compose(background, sprite)
