"""
Deeb Life OS — entry point.

Start order:
  1. Init SQLite (sync, before async loop)
  2. Build Telegram application
  3. post_init: start APScheduler inside the running event loop
  4. run_polling: blocking until SIGINT/SIGTERM
  5. post_shutdown: stop scheduler cleanly
"""
import logging
import sys

from telegram.ext import Application

import config
import database as db
import scheduler as sched
import telegram_bot as bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.INFO)
logging.getLogger("telegram").setLevel(logging.WARNING)


async def _post_init(application: Application) -> None:
    scheduler = sched.build_scheduler()
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info("Scheduler started — %d jobs registered", len(scheduler.get_jobs()))


async def _post_shutdown(application: Application) -> None:
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")


def main() -> None:
    logger.info("=== Deeb Life OS — starting up ===")
    db.init_db_sync()
    logger.info("Database ready: %s", config.DB_PATH)

    application = bot.build_app()
    application.post_init = _post_init
    application.post_shutdown = _post_shutdown

    logger.info("Starting Telegram polling...")
    application.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
