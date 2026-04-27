"""
Deeb Life Operating System — main entry point.

Start order:
  1. Init SQLite database
  2. Build & start APScheduler
  3. Build & run Telegram bot (blocking until SIGINT/SIGTERM)
  4. On shutdown: stop scheduler cleanly
"""
import asyncio
import logging
import signal
import sys

from telegram.ext import Application

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

# Suppress noisy library loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.INFO)
logging.getLogger("telegram").setLevel(logging.WARNING)


async def _post_init(application: Application) -> None:
    """Called by python-telegram-bot after the app initialises but before polling starts."""
    logger.info("Post-init: starting scheduler")
    scheduler = sched.build_scheduler()
    scheduler.start()
    # Attach scheduler to app so it can be stopped cleanly on shutdown
    application.bot_data["scheduler"] = scheduler
    logger.info("Scheduler started — %d jobs registered", len(scheduler.get_jobs()))


async def _post_shutdown(application: Application) -> None:
    """Called by python-telegram-bot during graceful shutdown."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")


def main() -> None:
    logger.info("=== Deeb Life OS — starting up ===")

    # 1. Sync DB init (before async loop starts)
    db.init_db_sync()
    logger.info("Database initialised at %s", __import__("config").DB_PATH)

    # 2. Build Telegram application
    application = bot.build_app()

    # Wire lifecycle hooks
    application.post_init = _post_init
    application.post_shutdown = _post_shutdown

    logger.info("Starting Telegram polling...")
    application.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
