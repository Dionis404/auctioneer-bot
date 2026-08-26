import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    database_url: str

    sfl_api_key: str | None

    alert_chat_id: int | None
    notify_chat_id: int | None
    admin_ids: list[int] = field(default_factory=list)

    site_image_base_url: str = "https://goblincodex.fun/sprites/"


def load_config() -> Config:
    alert_chat_id = os.getenv("ALERT_CHAT_ID")
    notify_chat_id = os.getenv("NOTIFY_CHAT_ID")

    return Config(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        database_url=_require("DATABASE_URL"),
        sfl_api_key=os.getenv("SFL_API_KEY"),
        alert_chat_id=int(alert_chat_id) if alert_chat_id else None,
        notify_chat_id=int(notify_chat_id) if notify_chat_id else None,
        admin_ids=_parse_ids(os.getenv("ADMIN_IDS")),
        site_image_base_url=os.getenv(
            "SITE_IMAGE_BASE_URL", "https://goblincodex.fun/sprites/"
        ),
    )
