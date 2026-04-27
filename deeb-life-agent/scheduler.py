"""
Proactive scheduler — drives all time-based events for the agent.

Uses APScheduler AsyncIOScheduler so all jobs share the Telegram bot event loop.
"""
import logging
from datetime import date, datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import ai_brain
import config
import database as db
import telegram_bot as bot

logger = logging.getLogger(__name__)


def build_scheduler() -> AsyncIOScheduler:
    tz = pytz.timezone(config.TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)

    def job(func, trigger, job_id, **kwargs):
        scheduler.add_job(func, trigger, id=job_id, replace_existing=True, **kwargs)

    # Morning check-in
    job(_morning_checkin,
        CronTrigger(hour=config.MORNING_CHECKIN_HOUR,
                    minute=config.MORNING_CHECKIN_MINUTE, timezone=tz),
        "morning_checkin")

    # Meal reminders
    for time_str, meal_name in [("08:30", "Breakfast"), ("13:00", "Lunch"),
                                  ("16:30", "Afternoon snack"), ("19:00", "Dinner")]:
        h, m = map(int, time_str.split(":"))
        job(_meal_reminder,
            CronTrigger(hour=h, minute=m, timezone=tz),
            f"meal_{meal_name.lower().replace(' ', '_')}",
            kwargs={"meal_name": meal_name})

    # Gym reminder Mon/Wed/Fri
    job(_gym_reminder,
        CronTrigger(day_of_week="mon,wed,fri", hour=7, minute=15, timezone=tz),
        "gym_reminder")

    # Job search Mon–Fri
    job(_job_reminder,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=30, timezone=tz),
        "job_reminder")

    # AI income Mon–Fri
    job(_ai_income_reminder,
        CronTrigger(day_of_week="mon-fri", hour=13, minute=30, timezone=tz),
        "ai_income_reminder")

    # Pre-task check every 30 min
    job(_check_upcoming_tasks,
        CronTrigger(minute="*/30", timezone=tz),
        "pretask_check")

    # Evening review
    job(_evening_review,
        CronTrigger(hour=config.EVENING_REVIEW_HOUR,
                    minute=config.EVENING_REVIEW_MINUTE, timezone=tz),
        "evening_review")

    # Protein check 20:00
    job(_protein_check,
        CronTrigger(hour=20, minute=0, timezone=tz),
        "protein_check")

    # Weekly report Sunday
    job(_weekly_report,
        CronTrigger(day_of_week=config.WEEKLY_REPORT_DAY,
                    hour=config.WEEKLY_REPORT_HOUR, timezone=tz),
        "weekly_report")

    # Adaptation engine Sunday 06:00
    job(_run_adaptation,
        CronTrigger(day_of_week="sun", hour=6, minute=0, timezone=tz),
        "adaptation_engine")

    # Follow-up checker every 2 min
    job(_followup_check,
        CronTrigger(minute="*/2", timezone=tz),
        "followup_check")

    # Journal prompt Tue/Thu 20:30
    job(_journal_prompt,
        CronTrigger(day_of_week="tue,thu", hour=20, minute=30, timezone=tz),
        "journal_prompt")

    return scheduler


# ── Job implementations ───────────────────────────────────────────────────────
async def _morning_checkin() -> None:
    logger.info("Scheduler: morning check-in")
    await bot.send_morning_checkin()


async def _meal_reminder(meal_name: str) -> None:
    logger.info("Scheduler: meal reminder — %s", meal_name)
    await bot.send_meal_reminder(meal_name)


async def _gym_reminder() -> None:
    tasks = await db.get_tasks_for_date(date.today().isoformat())
    gym_task = next((t for t in tasks if t["category"] == "gym" and not t["completed"]), None)
    if gym_task:
        logger.info("Scheduler: gym reminder")
        await bot.send_gym_reminder(gym_task)
    else:
        await bot.send(
            "*Morning movement.* No gym on today's plan.\n\n"
            "Even 20 minutes walking counts — moving today?\n\n"
            "→ Action: Reply 'yes' to log it or 'no' to skip."
        )


async def _job_reminder() -> None:
    stats = await db.get_job_stats(7)
    await bot.send(
        f"*Job search block — {datetime.now().strftime('%H:%M')}*\n\n"
        f"Applications this week: {stats['total']} / 15 target\n\n"
        "Open LinkedIn / Indeed right now.\n"
        "→ Action: Apply to 2 jobs in the next 30 minutes. Reply with company names when done."
    )


async def _ai_income_reminder() -> None:
    tasks = await db.get_tasks_for_date(date.today().isoformat())
    ai_task = next((t for t in tasks if t["category"] == "ai_income" and not t["completed"]), None)
    if ai_task:
        await bot.send_pre_task_reminder(ai_task)
    else:
        await bot.send(
            f"*AI income block — {datetime.now().strftime('%H:%M')}*\n\n"
            "No AI task on today's plan.\n\n"
            "Pick ONE:\n"
            "• Watch 1 tutorial on a tool you want to monetize\n"
            "• Build one small proof-of-concept\n"
            "• Send one outreach message\n\n"
            "→ Action: Pick one and reply which you're doing."
        )


async def _check_upcoming_tasks() -> None:
    today_str = date.today().isoformat()
    tasks = await db.get_tasks_for_date(today_str)
    now = datetime.now()

    for task in tasks:
        if task["completed"] or task["skipped"] or not task.get("scheduled_time"):
            continue
        try:
            task_time = datetime.strptime(f"{today_str} {task['scheduled_time']}", "%Y-%m-%d %H:%M")
            delta = (task_time - now).total_seconds() / 60
            if 10 <= delta <= 20:
                logger.info("Scheduler: pre-task reminder for '%s'", task["description"])
                await bot.send_pre_task_reminder(task)
        except ValueError:
            continue


async def _evening_review() -> None:
    logger.info("Scheduler: evening review")
    await bot.send_evening_review()


async def _protein_check() -> None:
    nutrition = await db.get_daily_nutrition(date.today().isoformat())
    remaining = config.MIN_PROTEIN_G - nutrition["protein_g"]
    if remaining > 10:
        await bot.send(
            f"*Protein check — 8 PM*\n\n"
            f"At {nutrition['protein_g']:.0f}g / {config.MIN_PROTEIN_G}g — {remaining:.0f}g still needed.\n\n"
            "→ Action: Protein shake or 150g chicken now. Do it before bed."
        )


async def _weekly_report() -> None:
    logger.info("Scheduler: weekly report")
    await bot.send_weekly_report()


async def _run_adaptation() -> None:
    logger.info("Scheduler: adaptation engine")
    analysis = await ai_brain.run_adaptation_engine()
    await bot.send(
        f"*Weekly Adaptation Complete*\n\n{analysis.get('summary', 'Done.')}\n\n"
        "Schedule and targets adjusted based on last week.\n"
        "Type /adapt for the full breakdown."
    )


async def _followup_check() -> None:
    await bot.process_pending_followups()


async def _journal_prompt() -> None:
    logger.info("Scheduler: journal prompt")
    await bot.send_journal_prompt()
