"""
Proactive scheduler — drives all time-based events for the agent.

Uses APScheduler with AsyncIOScheduler so everything runs inside the same
event loop as the Telegram bot.

Job inventory:
  morning_checkin        — 07:00 daily
  meal_reminder_*        — 08:30, 13:00, 19:00 daily
  gym_reminder           — 07:30 Mon/Wed/Fri
  job_reminder           — 09:30 Mon–Fri
  ai_income_reminder     — 13:30 Mon–Fri
  evening_review         — 21:00 daily
  weekly_report          — Sunday 08:00
  followup_check         — every 2 minutes
  adaptation_engine      — Sunday 06:00
  protein_check          — 20:00 daily
"""
import logging
from datetime import date, datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import database as db
import telegram_bot as bot

logger = logging.getLogger(__name__)


def build_scheduler() -> AsyncIOScheduler:
    tz = pytz.timezone(config.TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)

    # ── Morning check-in ──────────────────────────────────────────────────────
    scheduler.add_job(
        _morning_checkin,
        CronTrigger(
            hour=config.MORNING_CHECKIN_HOUR,
            minute=config.MORNING_CHECKIN_MINUTE,
            timezone=tz,
        ),
        id="morning_checkin",
        replace_existing=True,
    )

    # ── Meal reminders ────────────────────────────────────────────────────────
    meal_schedule = [
        ("08:30", "Breakfast"),
        ("13:00", "Lunch"),
        ("16:30", "Afternoon snack"),
        ("19:00", "Dinner"),
    ]
    for time_str, meal_name in meal_schedule:
        h, m = map(int, time_str.split(":"))
        scheduler.add_job(
            _meal_reminder,
            CronTrigger(hour=h, minute=m, timezone=tz),
            id=f"meal_{meal_name.lower().replace(' ', '_')}",
            kwargs={"meal_name": meal_name},
            replace_existing=True,
        )

    # ── Gym reminder (Mon, Wed, Fri) ──────────────────────────────────────────
    scheduler.add_job(
        _gym_reminder,
        CronTrigger(day_of_week="mon,wed,fri", hour=7, minute=15, timezone=tz),
        id="gym_reminder",
        replace_existing=True,
    )

    # ── Job search reminder (Mon–Fri) ─────────────────────────────────────────
    scheduler.add_job(
        _job_reminder,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=30, timezone=tz),
        id="job_reminder",
        replace_existing=True,
    )

    # ── AI income reminder (Mon–Fri) ──────────────────────────────────────────
    scheduler.add_job(
        _ai_income_reminder,
        CronTrigger(day_of_week="mon-fri", hour=13, minute=30, timezone=tz),
        id="ai_income_reminder",
        replace_existing=True,
    )

    # ── Pre-task reminders (every 30 minutes check) ───────────────────────────
    scheduler.add_job(
        _check_upcoming_tasks,
        CronTrigger(minute="*/30", timezone=tz),
        id="pretask_check",
        replace_existing=True,
    )

    # ── Evening review ────────────────────────────────────────────────────────
    scheduler.add_job(
        _evening_review,
        CronTrigger(
            hour=config.EVENING_REVIEW_HOUR,
            minute=config.EVENING_REVIEW_MINUTE,
            timezone=tz,
        ),
        id="evening_review",
        replace_existing=True,
    )

    # ── Protein check (20:00) ─────────────────────────────────────────────────
    scheduler.add_job(
        _protein_check,
        CronTrigger(hour=20, minute=0, timezone=tz),
        id="protein_check",
        replace_existing=True,
    )

    # ── Weekly report (Sunday) ────────────────────────────────────────────────
    scheduler.add_job(
        _weekly_report,
        CronTrigger(
            day_of_week=config.WEEKLY_REPORT_DAY,
            hour=config.WEEKLY_REPORT_HOUR,
            timezone=tz,
        ),
        id="weekly_report",
        replace_existing=True,
    )

    # ── Adaptation engine (Sunday early morning) ──────────────────────────────
    scheduler.add_job(
        _run_adaptation,
        CronTrigger(day_of_week="sun", hour=6, minute=0, timezone=tz),
        id="adaptation_engine",
        replace_existing=True,
    )

    # ── Follow-up checker (every 2 minutes) ───────────────────────────────────
    scheduler.add_job(
        _followup_check,
        CronTrigger(minute="*/2", timezone=tz),
        id="followup_check",
        replace_existing=True,
    )

    # ── Journal prompt (random-ish: Tue + Thu 20:30) ──────────────────────────
    scheduler.add_job(
        _journal_prompt,
        CronTrigger(day_of_week="tue,thu", hour=20, minute=30, timezone=tz),
        id="journal_prompt",
        replace_existing=True,
    )

    return scheduler


# ── Job implementations ───────────────────────────────────────────────────────
async def _morning_checkin() -> None:
    logger.info("Scheduler: sending morning check-in")
    await bot.send_morning_checkin()


async def _meal_reminder(meal_name: str) -> None:
    logger.info("Scheduler: meal reminder — %s", meal_name)
    await bot.send_meal_reminder(meal_name)


async def _gym_reminder() -> None:
    today_str = date.today().isoformat()
    tasks = await db.get_tasks_for_date(today_str)
    gym_task = next(
        (t for t in tasks if t["category"] == "gym" and not t["completed"]),
        None,
    )
    if gym_task:
        logger.info("Scheduler: gym reminder")
        await bot.send_gym_reminder(gym_task)
    else:
        # No planned gym task → light nudge anyway
        await bot.send(
            "*Morning movement.* No gym block on today's plan.\n\n"
            "Even 20 minutes of walking counts — are you moving today?\n\n"
            "→ Action: Reply 'yes' to log it or 'no' to skip."
        )


async def _job_reminder() -> None:
    today_str = date.today().isoformat()
    stats = await db.get_job_stats(7)
    applications_this_week = stats["total"]

    msg = (
        f"*Job search block — {datetime.now().strftime('%H:%M')}*\n\n"
        f"Applications this week: {applications_this_week}\n"
        "Target: 3–5 per day.\n\n"
        "Open LinkedIn / Indeed right now.\n"
        "→ Action: Apply to 2 jobs in the next 30 minutes. Reply with company names when done."
    )
    await bot.send(msg)


async def _ai_income_reminder() -> None:
    today_str = date.today().isoformat()
    tasks = await db.get_tasks_for_date(today_str)
    ai_task = next(
        (t for t in tasks if t["category"] == "ai_income" and not t["completed"]),
        None,
    )

    if ai_task:
        await bot.send_pre_task_reminder(ai_task)
    else:
        msg = (
            f"*AI income block — {datetime.now().strftime('%H:%M')}*\n\n"
            "No AI task on today's plan. That's a miss.\n\n"
            "Pick ONE:\n"
            "• Watch 1 tutorial on a tool you want to monetize\n"
            "• Build one small proof-of-concept\n"
            "• Send one outreach message\n\n"
            "→ Action: Pick and reply which one you're doing."
        )
        await bot.send(msg)


async def _check_upcoming_tasks() -> None:
    """Fire pre-task reminders 15 minutes before scheduled task time."""
    today_str = date.today().isoformat()
    tasks = await db.get_tasks_for_date(today_str)
    now = datetime.now()
    now_str = now.strftime("%H:%M")

    for task in tasks:
        if task["completed"] or task["skipped"]:
            continue
        scheduled = task.get("scheduled_time")
        if not scheduled:
            continue
        # Check if task starts in 10–20 minutes
        try:
            task_time = datetime.strptime(f"{today_str} {scheduled}", "%Y-%m-%d %H:%M")
            delta_minutes = (task_time - now).total_seconds() / 60
            if 10 <= delta_minutes <= 20:
                logger.info("Scheduler: pre-task reminder for %s", task["description"])
                await bot.send_pre_task_reminder(task)
        except ValueError:
            continue


async def _evening_review() -> None:
    logger.info("Scheduler: evening review")
    await bot.send_evening_review()


async def _protein_check() -> None:
    today_str = date.today().isoformat()
    nutrition = await db.get_daily_nutrition(today_str)
    remaining = config.MIN_PROTEIN_G - nutrition["protein_g"]

    if remaining > 10:
        msg = (
            f"*Protein check — 8 PM*\n\n"
            f"You're at {nutrition['protein_g']:.0f}g / {config.MIN_PROTEIN_G}g.\n"
            f"Still need {remaining:.0f}g before bed.\n\n"
            "→ Action: Have a protein shake or high-protein snack now. 30g protein = 1 scoop whey or 150g chicken."
        )
        await bot.send(msg)


async def _weekly_report() -> None:
    logger.info("Scheduler: weekly report")
    await bot.send_weekly_report()


async def _run_adaptation() -> None:
    logger.info("Scheduler: running adaptation engine")
    import ai_brain
    analysis = await ai_brain.run_adaptation_engine()
    summary = analysis.get("summary", "Adaptation complete.")
    await bot.send(
        f"*Weekly Adaptation Complete*\n\n{summary}\n\n"
        "Your schedule and targets have been adjusted based on last week's performance.\n"
        "Type /adapt to see the full breakdown."
    )


async def _followup_check() -> None:
    await bot.process_pending_followups()


async def _journal_prompt() -> None:
    logger.info("Scheduler: journal prompt")
    await bot.send_journal_prompt()
