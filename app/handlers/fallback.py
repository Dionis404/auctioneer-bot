import logging

from aiogram import F, Router
from aiogram.types import ErrorEvent, Message

from app.config import Config

logger = logging.getLogger(__name__)

router = Router(name="fallback")

KNOWN_ADMIN_COMMANDS = "/status, /update_auctions, /test_notification"

BOT_INFO_TEXT = (
    "Я бот для уведомлений об аукционах Sunflower Land.\n"
    "Я не отправляю сообщения в личку — все уведомления публикуются только "
    'в <a href="https://t.me/+hSm5ZeGb7ohhYzhi">чате</a>\n'
    'Историю аукционов можно посмотреть на '
    '<a href="https://goblincodex.fun/">сайте</a>'
)


def _is_admin(message: Message, config: Config) -> bool:
    return message.from_user is not None and message.from_user.id in config.admin_ids


@router.message(F.text.startswith("/"))
async def cmd_unknown(message: Message, config: Config) -> None:
    if _is_admin(message, config):
        await message.answer(
            f"Не знаю такую команду. Доступные: {KNOWN_ADMIN_COMMANDS}"
        )
    else:
        await message.answer("Неизвестная команда")


@router.message()
async def handle_plain_text(message: Message) -> None:
    if message.chat.type == "private":
        await message.answer(BOT_INFO_TEXT)


async def handle_error(event: ErrorEvent) -> None:
    logger.exception(
        "Unhandled exception while processing update %s",
        event.update.update_id,
        exc_info=event.exception,
    )
