import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import load_config
from app.db import create_pool, run_migrations
from app.handlers import commands, fallback
from app.image_compose import close_client as close_image_client
from app.jobs.auctions import schedule_all_pending
from app.sfl_client import close_client as close_sfl_client
from app.sfl_client import init_client as init_sfl_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()

    pool = await create_pool(config.database_url)
    await run_migrations(pool)

    init_sfl_client()

    bot = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher["config"] = config
    dispatcher["db_pool"] = pool

    dispatcher.include_router(commands.router)
    dispatcher.include_router(fallback.router)
    dispatcher.errors.register(fallback.handle_error)

    scheduler = AsyncIOScheduler()
    dispatcher["scheduler"] = scheduler

    scheduler.start()

    await schedule_all_pending(bot, pool, scheduler, config)

    try:
        logger.info("Starting bot polling")
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await close_image_client()
        await close_sfl_client()
        await pool.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
