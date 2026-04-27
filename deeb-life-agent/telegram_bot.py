"""
Telegram bot — two-way communication layer.

Handles:
- Inbound message classification and routing
- Outbound proactive messages (called by scheduler)
- Follow-up logic (no response → follow up after FOLLOWUP_MINUTES)
- Daily plan delivery after morning check-in
"""
import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import ai_brain
import config
import database as db

logger = logging.getLogger(__name__)

# Module-level application handle (set in build_app)
_app: Optional[Application] = None

# Tracks pending check-in state: {chat_id: "awaiting_morning_stats" | "awaiting_journal" | None}
_pending_state: dict[int, str] = {}
# Tracks last outbound message time for follow-up logic
_last_outbound: dict[int, datetime] = {}
# Count follow-up attempts per context key
_followup_count: dict[str, int] = {}


# ── App builder ───────────────────────────────────────────────────────────────
def build_app() -> Application:
    global _app
    _app = (
        Application.builder()
        .token(config.TELEGRAM_TOKEN)
        .build()
    )
    _app.add_handler(CommandHandler("start", cmd_start))
    _app.add_handler(CommandHandler("status", cmd_status))
    _app.add_handler(CommandHandler("tasks", cmd_tasks))
    _app.add_handler(CommandHandler("nutrition", cmd_nutrition))
    _app.add_handler(CommandHandler("weight", cmd_weight))
    _app.add_handler(CommandHandler("jobs", cmd_jobs))
    _app.add_handler(CommandHandler("plan", cmd_plan))
    _app.add_handler(CommandHandler("review", cmd_review))
    _app.add_handler(CommandHandler("adapt", cmd_adapt))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return _app


# ── Utility: send a message ───────────────────────────────────────────────────
async def send(text: str, chat_id: Optional[str] = None) -> None:
    cid = chat_id or config.TELEGRAM_CHAT_ID
    if _app is None:
        logger.error("Telegram app not initialised — cannot send message.")
        return
    await _app.bot.send_message(chat_id=cid, text=text, parse_mode="Markdown")
    _last_outbound[int(cid)] = datetime.utcnow()
    await db.save_message(
        direction="outbound",
        content=text,
        telegram_id=int(cid),
    )


# ── Inbound message handler ───────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if msg is None or msg.text is None:
        return

    chat_id = msg.chat_id
    text = msg.text.strip()
    today_str = date.today().isoformat()

    # Persist raw inbound message
    await db.save_message(direction="inbound", content=text, telegram_id=chat_id)

    # Classify message
    classified = await ai_brain.classify_message(text)
    msg_type = classified.get("type", "general")
    data = classified.get("structured_data", {})

    # Route based on classification
    await _route_message(chat_id, text, msg_type, data, today_str)

    # Update follow-up responded status
    pending = await db.get_pending_followups()
    for fu in pending:
        if fu["sent"] and not fu["responded"]:
            await db.mark_followup_responded(fu["id"])


async def _route_message(
    chat_id: int, text: str, msg_type: str, data: dict, today_str: str
) -> None:
    """Dispatch inbound message to the correct handler and reply."""

    # ── Morning check-in responses ──
    pending = _pending_state.get(chat_id)

    if pending == "awaiting_morning_stats":
        await _process_morning_stats(chat_id, text, data, today_str)
        return

    if pending == "awaiting_journal":
        response = await ai_brain.generate_response(text, "journal", data)
        await send(response, str(chat_id))
        _pending_state.pop(chat_id, None)
        return

    # ── Weight log ──
    if msg_type == "weight_log" and data.get("weight_kg"):
        weight = float(data["weight_kg"])
        await db.log_weight(today_str, weight)
        response = await ai_brain.generate_response(text, msg_type, data)
        await send(response, str(chat_id))
        return

    # ── Meal log ──
    if msg_type == "meal_log" and data.get("food_description"):
        food = data["food_description"]
        nutrition = await ai_brain.estimate_nutrition(food)
        if not data.get("protein_g"):
            data["protein_g"] = nutrition["protein_g"]
        if not data.get("calories"):
            data["calories"] = nutrition["calories"]
        await db.log_meal(
            today_str,
            food,
            protein_g=float(data.get("protein_g") or 0),
            calories=int(data.get("calories") or 0),
            raw_message=text,
        )
        response = await ai_brain.generate_response(text, msg_type, data)
        await send(response, str(chat_id))
        return

    # ── Workout log ──
    if msg_type == "workout_log":
        completed = bool(data.get("workout_completed"))
        await db.log_workout(
            today_str,
            completed=completed,
            duration_m=data.get("workout_duration_m"),
            notes=text,
        )
        tasks = await db.get_tasks_for_date(today_str)
        gym_task = next((t for t in tasks if t["category"] == "gym" and not t["completed"]), None)
        if gym_task and completed:
            await db.complete_task(gym_task["id"])
        response = await ai_brain.generate_response(text, msg_type, data)
        await send(response, str(chat_id))
        return

    # ── Job task ──
    if msg_type == "job_task":
        count = data.get("jobs_applied") or 1
        for _ in range(int(count)):
            await db.log_job_application(
                today_str,
                company=data.get("company"),
                position=data.get("position"),
                notes=text,
            )
        response = await ai_brain.generate_response(text, msg_type, data)
        await send(response, str(chat_id))
        return

    # ── AI income task ──
    if msg_type == "ai_task":
        await db.log_ai_income_task(
            today_str,
            task_type=data.get("ai_task_type", "general"),
            description=data.get("ai_task_description", text),
            completed=True,
            notes=text,
        )
        response = await ai_brain.generate_response(text, msg_type, data)
        await send(response, str(chat_id))
        return

    # ── Mood/energy update ──
    if msg_type == "mood_energy":
        await db.upsert_checkin(
            today_str,
            energy=data.get("energy_level"),
            mood=data.get("mood_level"),
        )
        response = await ai_brain.generate_response(text, msg_type, data)
        await send(response, str(chat_id))
        return

    # ── General fallback ──
    response = await ai_brain.generate_response(text, msg_type, data)
    await send(response, str(chat_id))


async def _process_morning_stats(
    chat_id: int, text: str, data: dict, today_str: str
) -> None:
    """Parse morning check-in stats and generate the daily plan."""
    # Try to parse explicit fields from classification data first
    energy = _parse_int_or_ai(data.get("energy_level"), 5)
    mood = _parse_int_or_ai(data.get("mood_level"), 5)
    appetite = _parse_int_or_ai(data.get("mood_level"), 5)  # re-use if not separate
    sleep_hrs = float(data.get("sleep_hrs") or 7.0)

    await db.upsert_checkin(
        today_str,
        energy=energy,
        mood=mood,
        appetite=appetite,
        sleep_hrs=sleep_hrs,
    )

    await send("Got it. Building your plan for today...", str(chat_id))

    plan = await ai_brain.generate_daily_plan(energy, mood, appetite, sleep_hrs)

    # Store tasks in DB
    for task in plan.get("tasks", []):
        await db.create_task(
            today_str,
            tier=task["tier"],
            category=task["category"],
            description=task["description"],
            scheduled_time=task.get("scheduled_time"),
        )

    # Format and send the plan
    plan_text = _format_daily_plan(plan)
    await send(plan_text, str(chat_id))

    # Schedule calendar events
    try:
        from calendar_manager import sync_tasks_to_calendar
        await sync_tasks_to_calendar(plan.get("tasks", []))
    except Exception as exc:
        logger.warning("Calendar sync failed: %s", exc)

    _pending_state.pop(chat_id, None)


def _parse_int_or_ai(value, default: int) -> int:
    try:
        return max(1, min(10, int(float(value)))) if value is not None else default
    except (ValueError, TypeError):
        return default


def _format_daily_plan(plan: dict) -> str:
    lines = ["*Your Plan for Today*\n"]

    tiers = {"gold": "🥇 Gold", "silver": "🥈 Silver", "bronze": "🥉 Bronze"}
    grouped: dict[str, list] = {"gold": [], "silver": [], "bronze": []}
    for task in plan.get("tasks", []):
        grouped[task["tier"]].append(task)

    for tier_key, tier_label in tiers.items():
        tasks = grouped[tier_key]
        if not tasks:
            continue
        lines.append(f"*{tier_label}*")
        for t in tasks:
            time_str = f"[{t.get('scheduled_time', '?')}] " if t.get("scheduled_time") else ""
            lines.append(f"  {time_str}{t['description']}")
        lines.append("")

    if plan.get("energy_note"):
        lines.append(f"_Note: {plan['energy_note']}_")
    if plan.get("recovery_note"):
        lines.append(f"_Recovery plan: {plan['recovery_note']}_")

    lines.append("\nReply to each task when done. I'll check in on you.")
    return "\n".join(lines)


# ── Proactive senders (called by scheduler) ───────────────────────────────────
async def send_morning_checkin() -> None:
    msg = await ai_brain.generate_morning_checkin()
    await send(msg)
    _pending_state[int(config.TELEGRAM_CHAT_ID)] = "awaiting_morning_stats"
    # Schedule a follow-up in case Deeb doesn't respond
    await _schedule_followup(
        context="morning check-in — no response yet",
        key="morning_checkin",
    )


async def send_pre_task_reminder(task: dict) -> None:
    msg = await ai_brain.generate_pre_task_reminder(task)
    await send(msg)
    await _schedule_followup(
        context=f"pre-task reminder for: {task['description']}",
        key=f"pretask_{task['id']}",
        task_id=task["id"],
    )


async def send_post_task_checkin(task: dict) -> None:
    msg = await ai_brain.generate_post_task_checkin(task)
    await send(msg)


async def send_evening_review() -> None:
    msg = await ai_brain.generate_evening_review()
    await send(msg)


async def send_weekly_report() -> None:
    msg = await ai_brain.generate_weekly_report()
    await send(msg)


async def send_meal_reminder(meal_name: str) -> None:
    today_str = date.today().isoformat()
    nutrition = await db.get_daily_nutrition(today_str)
    protein_remaining = config.MIN_PROTEIN_G - nutrition["protein_g"]
    cal_remaining = config.TARGET_CALORIES - nutrition["calories"]

    msg = (
        f"*{meal_name} time.*\n\n"
        f"Protein today: {nutrition['protein_g']:.0f}g / {config.MIN_PROTEIN_G}g "
        f"({'✓' if nutrition['protein_g'] >= config.MIN_PROTEIN_G else f'{protein_remaining:.0f}g remaining'})\n"
        f"Calories: {nutrition['calories']} / {config.TARGET_CALORIES} "
        f"({'✓' if nutrition['calories'] >= config.TARGET_CALORIES else f'{cal_remaining} remaining'})\n\n"
        "What did you eat? Log it now."
    )
    await send(msg)
    await _schedule_followup(
        context=f"{meal_name} — Deeb hasn't logged a meal yet",
        key=f"meal_{meal_name.lower()}",
    )


async def send_gym_reminder(task: dict) -> None:
    streak = await db.get_workout_streak()
    msg = (
        f"*Gym time.* Current streak: {streak} days.\n\n"
        f"Task: {task['description']}\n\n"
        "Are you heading out? Reply 'yes', 'done', or 'skipping'."
    )
    await send(msg)
    await _schedule_followup(
        context=f"gym reminder — no response to workout check-in",
        key=f"gym_{date.today().isoformat()}",
        task_id=task.get("id"),
    )


async def send_journal_prompt() -> None:
    msg = await ai_brain.generate_journal_prompt()
    await send(msg)
    _pending_state[int(config.TELEGRAM_CHAT_ID)] = "awaiting_journal"


async def process_pending_followups() -> None:
    """Called every minute by the scheduler to dispatch due follow-ups."""
    pending = await db.get_pending_followups()
    for fu in pending:
        if not fu["sent"] and not fu["responded"]:
            key = fu["context"] or str(fu["id"])
            attempt = _followup_count.get(key, 0) + 1
            _followup_count[key] = attempt

            if attempt <= config.MAX_FOLLOWUPS:
                msg = await ai_brain.generate_followup(fu["context"] or "a pending task", attempt)
                await send(msg)
            await db.mark_followup_sent(fu["id"])


async def _schedule_followup(
    context: str, key: str, task_id: Optional[int] = None
) -> None:
    scheduled_at = (
        datetime.utcnow() + timedelta(minutes=config.FOLLOWUP_MINUTES)
    ).strftime("%Y-%m-%d %H:%M:%S")
    await db.create_followup(task_id=task_id, scheduled_at=scheduled_at, context=context)


# ── Command handlers ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🟢 *Deeb Life OS is active.*\n\n"
        "I'll send your morning check-in at 7 AM and keep you on track throughout the day.\n\n"
        "Commands:\n"
        "/status — quick daily summary\n"
        "/tasks — today's task list\n"
        "/nutrition — today's food log\n"
        "/weight — log or view weight\n"
        "/jobs — job search stats\n"
        "/plan — regenerate today's plan\n"
        "/review — trigger evening review\n"
        "/adapt — run adaptation engine",
        parse_mode="Markdown",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today_str = date.today().isoformat()
    tasks = await db.get_tasks_for_date(today_str)
    nutrition = await db.get_daily_nutrition(today_str)
    checkin = await db.get_checkin(today_str) or {}
    streak = await db.get_workout_streak()

    completed = sum(1 for t in tasks if t["completed"])
    total = len(tasks)
    gold_done = sum(1 for t in tasks if t["tier"] == "gold" and t["completed"])
    gold_total = sum(1 for t in tasks if t["tier"] == "gold")

    msg = (
        f"*Status — {today_str}*\n\n"
        f"Energy: {checkin.get('energy', '?')}/10  |  Mood: {checkin.get('mood', '?')}/10\n"
        f"Tasks: {completed}/{total} done  |  Gold: {gold_done}/{gold_total}\n"
        f"Protein: {nutrition['protein_g']:.0f}g / {config.MIN_PROTEIN_G}g\n"
        f"Calories: {nutrition['calories']} / {config.TARGET_CALORIES}\n"
        f"Workout streak: {streak} days\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today_str = date.today().isoformat()
    tasks = await db.get_tasks_for_date(today_str)

    if not tasks:
        await update.message.reply_text("No tasks planned today yet. Send /plan to generate them.")
        return

    lines = [f"*Tasks — {today_str}*\n"]
    for tier in ("gold", "silver", "bronze"):
        tier_tasks = [t for t in tasks if t["tier"] == tier]
        if not tier_tasks:
            continue
        emoji = {"gold": "🥇", "silver": "🥈", "bronze": "🥉"}[tier]
        lines.append(f"*{emoji} {tier.title()}*")
        for t in tier_tasks:
            status = "✅" if t["completed"] else ("⏭" if t["skipped"] else "⬜")
            time_str = f"[{t['scheduled_time']}] " if t.get("scheduled_time") else ""
            lines.append(f"  {status} {time_str}{t['description']}")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_nutrition(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today_str = date.today().isoformat()
    meals = await db.get_meals_for_date(today_str)
    nutrition = await db.get_daily_nutrition(today_str)

    lines = [f"*Nutrition — {today_str}*\n"]
    for m in meals:
        lines.append(f"  [{m['time']}] {m['description']} — {m['protein_g']:.0f}g protein, {m['calories']} kcal")
    lines.append(f"\n*Total:* {nutrition['protein_g']:.0f}g protein / {nutrition['calories']} kcal")
    lines.append(f"Protein target: {config.MIN_PROTEIN_G}g — {'✅ Met' if nutrition['protein_g'] >= config.MIN_PROTEIN_G else '❌ Not yet'}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if args:
        try:
            weight = float(args[0])
            today_str = date.today().isoformat()
            await db.log_weight(today_str, weight)
            history = await db.get_weight_history(7)
            trend = ""
            if len(history) >= 2:
                delta = history[0]["weight_kg"] - history[-1]["weight_kg"]
                trend = f" (+{delta:.1f}kg this week)" if delta > 0 else f" ({delta:.1f}kg this week)"
            await update.message.reply_text(
                f"Weight logged: *{weight} kg*{trend}", parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("Usage: /weight 74.5")
    else:
        history = await db.get_weight_history(14)
        if not history:
            await update.message.reply_text("No weight data yet. Use /weight 74.5 to log.")
            return
        lines = ["*Weight history (14d)*\n"]
        for row in history:
            lines.append(f"  {row['date']}: {row['weight_kg']:.1f} kg")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    stats_7 = await db.get_job_stats(7)
    stats_30 = await db.get_job_stats(30)
    msg = (
        "*Job Search Stats*\n\n"
        f"Last 7 days: {stats_7['total']} applications, {stats_7['interviews']} interviews\n"
        f"Last 30 days: {stats_30['total']} applications, {stats_30['interviews']} interviews\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today_str = date.today().isoformat()
    checkin = await db.get_checkin(today_str)
    if checkin:
        energy = checkin.get("energy", 6)
        mood = checkin.get("mood", 6)
        appetite = checkin.get("appetite", 6)
        sleep_hrs = checkin.get("sleep_hrs", 7.0)
    else:
        energy, mood, appetite, sleep_hrs = 6, 6, 6, 7.0

    await update.message.reply_text("Generating your plan...")
    plan = await ai_brain.generate_daily_plan(energy, mood, appetite, sleep_hrs)

    for task in plan.get("tasks", []):
        await db.create_task(
            today_str,
            tier=task["tier"],
            category=task["category"],
            description=task["description"],
            scheduled_time=task.get("scheduled_time"),
        )

    plan_text = _format_daily_plan(plan)
    await update.message.reply_text(plan_text, parse_mode="Markdown")


async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Generating evening review...")
    review = await ai_brain.generate_evening_review()
    await update.message.reply_text(review, parse_mode="Markdown")


async def cmd_adapt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Running adaptation engine on last 7 days...")
    analysis = await ai_brain.run_adaptation_engine()
    summary = analysis.get("summary", "Analysis complete.")
    recs = analysis.get("recommendations", {})
    msg = (
        f"*Adaptation Engine — Complete*\n\n"
        f"{summary}\n\n"
        f"*Adjustments:*\n"
        f"• Task difficulty: {recs.get('task_difficulty', 'maintain')}\n"
        f"• Calorie adjustment: {recs.get('calorie_adjustment', 'maintain')}\n"
        f"• Schedule changes: {'; '.join(recs.get('schedule_adjustments', ['none']))}\n\n"
        "Behavior patterns updated ✓"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")
