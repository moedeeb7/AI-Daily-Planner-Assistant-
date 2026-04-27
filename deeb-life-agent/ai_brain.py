"""
AI reasoning engine — all Claude API calls go through here.
Every public function returns a plain string (reply) or a dict (structured plan).
"""
import asyncio
import json
import re
from datetime import date, datetime
from typing import Optional

import anthropic

import config
import database as db

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

# ── Memory cache (invalidated when any .md file changes) ─────────────────────
_memory_cache: Optional[tuple[float, str]] = None  # (max_mtime, content)


def _load_memory() -> str:
    global _memory_cache
    md_files = sorted(config.MEMORY_DIR.glob("*.md"))
    if not md_files:
        return ""
    max_mtime = max(f.stat().st_mtime for f in md_files)
    if _memory_cache and _memory_cache[0] >= max_mtime:
        return _memory_cache[1]
    parts = [
        f"### {f.stem.replace('_', ' ').title()}\n{f.read_text(encoding='utf-8').strip()}"
        for f in md_files
        if f.read_text(encoding="utf-8").strip()
    ]
    content = "\n\n".join(parts)
    _memory_cache = (max_mtime, content)
    return content


def _load_prompt(name: str) -> str:
    path = config.PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def _build_system_prompt() -> str:
    return f"""You are Deeb's personal AI Life Operating System — direct, structured, action-focused.

Your role: daily assistant, life coach, schedule manager, fitness/weight-gain coach, job search manager, AI income strategist.

## Core rules
- Always output: (1) what matters now, (2) the next concrete action, (3) why it matters.
- Never give generic advice. Ground everything in Deeb's real situation and data.
- Tone: direct, practical. Supportive but not soft. Zero fluff.
- If Deeb fails: recover the day — do NOT reset everything.
- Keep responses under 250 words unless generating a full daily plan.
- Use short paragraphs or bullet points. Never walls of text.
- Always end with a single specific "→ Action:" line.

## Deeb's permanent memory
{_load_memory()}

## Current date
{date.today().isoformat()} ({datetime.now().strftime('%A')})
"""


def _strip_json(raw: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)


# ── Message classifier ────────────────────────────────────────────────────────
VALID_MSG_TYPES = {
    "weight_log", "meal_log", "workout_log", "job_task", "ai_task",
    "journal", "mood_energy", "general", "checkin_response",
    "task_completion", "skip_report",
}


async def classify_message(text: str) -> dict:
    prompt = f"""Classify this message from Deeb and extract structured data.

Message: "{text}"

Return ONLY valid JSON with this shape:
{{
  "type": "<one of: {', '.join(sorted(VALID_MSG_TYPES))}>",
  "summary": "<one sentence>",
  "structured_data": {{
    "weight_kg": null,
    "food_description": null,
    "protein_g": null,
    "calories": null,
    "workout_completed": null,
    "workout_duration_m": null,
    "jobs_applied": null,
    "company": null,
    "position": null,
    "ai_task_type": null,
    "ai_task_description": null,
    "energy_level": null,
    "mood_level": null,
    "appetite_level": null,
    "sleep_hrs": null
  }}
}}

Fill only relevant fields. Use null for everything else. Return JSON only."""

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=512,
        system="You are a JSON extraction engine. Return only valid JSON, nothing else.",
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        return json.loads(_strip_json(resp.content[0].text))
    except json.JSONDecodeError:
        return {"type": "general", "summary": text[:100], "structured_data": {}}


# ── Morning check-in ──────────────────────────────────────────────────────────
async def generate_morning_checkin() -> str:
    prompt_template = _load_prompt("morning_checkin")
    today_str = date.today().isoformat()

    weekly_summary, latest_weight = await asyncio.gather(
        db.get_weekly_summary(7),
        db.get_latest_weight(),
    )

    context = (
        f"Today: {today_str} ({datetime.now().strftime('%A')})\n"
        f"Latest weight: {latest_weight['weight_kg'] if latest_weight else 'unknown'} kg\n"
        f"7-day task completion: {json.dumps(weekly_summary.get('task_completion', {}))}\n"
        f"Workout streak: {weekly_summary.get('workout_streak', 0)} days"
    )

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=300,
        system=_build_system_prompt(),
        messages=[{
            "role": "user",
            "content": f"{prompt_template}\n\nContext:\n{context}\n\nGenerate today's morning check-in. Ask energy (1-10), mood (1-10), appetite (1-10), sleep hours. Max 120 words.",
        }],
    )
    return resp.content[0].text.strip()


# ── Daily plan generator ──────────────────────────────────────────────────────
async def generate_daily_plan(energy: int, mood: int, appetite: int, sleep_hrs: float) -> dict:
    today_str = date.today().isoformat()

    nutrition, job_stats, completion = await asyncio.gather(
        db.get_daily_nutrition(today_str),
        db.get_job_stats(7),
        db.get_task_completion_rate(7),
    )

    if energy >= 7:
        energy_rule = "High energy → deep work blocks, full gym session"
    elif energy >= 5:
        energy_rule = "Medium energy → structured tasks, standard gym"
    else:
        energy_rule = "Low energy → recovery + light tasks only"

    prompt = f"""Today: {today_str} ({datetime.now().strftime('%A')})
Deeb's morning — Energy: {energy}/10, Mood: {mood}/10, Appetite: {appetite}/10, Sleep: {sleep_hrs}h

Weekly: job applications={job_stats['total']}, completion={json.dumps(completion)}
Energy rule: {energy_rule}

Generate a realistic daily plan as JSON:
{{
  "tasks": [
    {{"tier": "gold|silver|bronze", "category": "gym|diet|job|ai_income|habit|other",
      "description": "...", "scheduled_time": "HH:MM", "rationale": "one line"}}
  ],
  "energy_note": "...",
  "recovery_note": "..."
}}

Rules:
- Exactly {config.DAILY_GOLD_REQUIRED} gold, {config.DAILY_SILVER_REQUIRED} silver, {config.DAILY_BRONZE_REQUIRED} bronze
- energy < 5: lighter gold task (30-min walk not full gym)
- mood < 5: reduce cognitive tasks, add recovery habit
- sleep < 6: rest block, push deep work to afternoon
- Space tasks realistically — no impossible stacking
- Return ONLY the JSON, no markdown"""

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        return json.loads(_strip_json(resp.content[0].text))
    except json.JSONDecodeError:
        return {
            "tasks": [],
            "energy_note": "Plan generation failed — defaulting to core habits.",
            "recovery_note": "Focus on gym, 1 job application, protein intake.",
        }


# ── Context-aware response ────────────────────────────────────────────────────
async def generate_response(user_message: str, msg_type: str, metadata: dict) -> str:
    today_str = date.today().isoformat()

    checkin, tasks, nutrition, incomplete_gold = await asyncio.gather(
        db.get_checkin(today_str),
        db.get_tasks_for_date(today_str),
        db.get_daily_nutrition(today_str),
        db.get_incomplete_gold_tasks(today_str),
    )
    checkin = checkin or {}

    completed_count = sum(1 for t in tasks if t["completed"])
    context = (
        f"Today check-in: energy={checkin.get('energy','?')}, mood={checkin.get('mood','?')}\n"
        f"Nutrition: {nutrition['protein_g']}g protein, {nutrition['calories']} kcal\n"
        f"Tasks: {completed_count}/{len(tasks)} done\n"
        f"Pending gold: {[t['description'] for t in incomplete_gold]}\n"
        f"Message type: {msg_type}"
    )

    recent_conv = await db.get_recent_conversation(6)
    history = [
        {"role": "user" if m["direction"] == "inbound" else "assistant", "content": m["content"]}
        for m in reversed(recent_conv)
    ]
    history.append({"role": "user", "content": f"[Context]\n{context}\n\nDeeb says: {user_message}"})

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=config.MAX_TOKENS,
        system=_build_system_prompt(),
        messages=history,
    )
    return resp.content[0].text.strip()


# ── Pre-task reminder ─────────────────────────────────────────────────────────
async def generate_pre_task_reminder(task: dict) -> str:
    checkin = await db.get_checkin(date.today().isoformat()) or {}

    prompt = (
        f"Pre-task reminder for: {task['description']} "
        f"(tier: {task['tier']}, cat: {task['category']}, "
        f"time: {task.get('scheduled_time', 'now')}, "
        f"energy: {checkin.get('energy', 5)}/10)\n\n"
        "Under 80 words. Direct. One readiness question. End with '→ Action:' line."
    )
    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=200,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


# ── Post-task check-in ────────────────────────────────────────────────────────
async def generate_post_task_checkin(task: dict) -> str:
    prompt = (
        f"Post-task check-in for: {task['description']} (category: {task['category']})\n\n"
        "Ask: 1) Completed? 2) Energy after (1-10)? 3) Effort (1-10)?\n"
        "Max 60 words. Direct. No fluff."
    )
    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=150,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


# ── Evening review ────────────────────────────────────────────────────────────
async def generate_evening_review() -> str:
    today_str = date.today().isoformat()

    tasks, nutrition, checkin = await asyncio.gather(
        db.get_tasks_for_date(today_str),
        db.get_daily_nutrition(today_str),
        db.get_checkin(today_str),
    )
    checkin = checkin or {}

    completed = [t for t in tasks if t["completed"]]
    skipped   = [t for t in tasks if t["skipped"]]
    missed    = [t for t in tasks if not t["completed"] and not t["skipped"]]

    context = (
        f"Date: {today_str}\n"
        f"Morning: energy={checkin.get('energy','?')}/10, mood={checkin.get('mood','?')}/10\n"
        f"Completed ({len(completed)}): {[t['description'] for t in completed]}\n"
        f"Skipped ({len(skipped)}): {[t['description'] for t in skipped]}\n"
        f"Missed ({len(missed)}): {[t['description'] for t in missed]}\n"
        f"Nutrition: {nutrition['protein_g']:.0f}g protein, {nutrition['calories']} kcal\n"
        f"Protein target {config.MIN_PROTEIN_G}g: "
        f"{'MET ✓' if nutrition['protein_g'] >= config.MIN_PROTEIN_G else 'MISSED ✗'}"
    )

    prompt = _load_prompt("evening_review") + f"\n\nToday's data:\n{context}"
    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=500,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


# ── Follow-up message ─────────────────────────────────────────────────────────
async def generate_followup(context_note: str, attempt: int = 1) -> str:
    simplify_note = (
        "No response received — simplify the ask to one tiny action."
        if attempt > 1 else "Be direct and brief."
    )
    prompt = (
        f"Follow-up #{attempt} for Deeb.\nContext: {context_note}\n{simplify_note}\n"
        "Max 60 words. End with one question or one action."
    )
    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=150,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


# ── Weekly report ─────────────────────────────────────────────────────────────
async def generate_weekly_report() -> str:
    summary = await db.get_weekly_summary(7)
    prompt_template = _load_prompt("weekly_review")
    context = json.dumps(summary, indent=2, default=str)

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=800,
        system=_build_system_prompt(),
        messages=[{
            "role": "user",
            "content": (
                f"{prompt_template}\n\nWeekly data:\n{context}\n\n"
                "Generate the weekly report. Max 400 words. "
                "Sections: Wins, Misses, Pattern Spotted, Next Week Focus."
            ),
        }],
    )
    return resp.content[0].text.strip()


# ── Adaptation engine ─────────────────────────────────────────────────────────
async def run_adaptation_engine() -> dict:
    summary, energy_trend, task_rates, weight_hist = await asyncio.gather(
        db.get_weekly_summary(7),
        db.get_energy_trend(7),
        db.get_task_completion_rate(7),
        db.get_weight_history(7),
    )
    prompt_template = _load_prompt("adaptation_prompt")

    context = (
        f"Task completion: {json.dumps(task_rates)}\n"
        f"Energy trend: {json.dumps(energy_trend, default=str)}\n"
        f"Weight history: {json.dumps(weight_hist, default=str)}\n"
        f"Job stats: {json.dumps(summary.get('job_stats', {}))}\n"
        f"Nutrition avg: {json.dumps(summary.get('nutrition', {}))}\n"
        f"Workout streak: {summary.get('workout_streak', 0)}"
    )

    analysis_prompt = f"""{prompt_template}

Data from last 7 days:
{context}

Return ONLY valid JSON:
{{
  "missed_task_patterns": ["..."],
  "best_performance_times": ["morning"],
  "energy_trend": "improving|declining|stable",
  "successful_habits": ["..."],
  "recommendations": {{
    "schedule_adjustments": ["..."],
    "task_difficulty": "increase|decrease|maintain",
    "habit_frequency": {{"gym": "daily|5x|3x", "journaling": "daily|3x|weekly"}},
    "calorie_adjustment": "increase|maintain|decrease",
    "protein_adjustment": "increase|maintain"
  }},
  "summary": "2-sentence plain-English summary"
}}"""

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": analysis_prompt}],
    )
    try:
        analysis = json.loads(_strip_json(resp.content[0].text))
    except json.JSONDecodeError:
        analysis = {"summary": "Adaptation engine parse error.", "raw": resp.content[0].text}

    _update_behavior_patterns(analysis)
    _append_adaptation_log(analysis)
    await db.save_behavior_snapshot(date.today().isoformat(), analysis)
    return analysis


def _update_behavior_patterns(analysis: dict) -> None:
    path = config.MEMORY_DIR / "behavior_patterns.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    recs = analysis.get("recommendations", {})
    block = (
        f"\n## Update: {date.today().isoformat()}\n\n"
        f"**Energy trend:** {analysis.get('energy_trend', 'unknown')}\n"
        f"**Best times:** {', '.join(analysis.get('best_performance_times', []))}\n"
        f"**Successful habits:** {', '.join(analysis.get('successful_habits', []))}\n"
        f"**Missed patterns:** {', '.join(analysis.get('missed_task_patterns', []))}\n\n"
        f"Schedule: {'; '.join(recs.get('schedule_adjustments', []))}\n"
        f"Task difficulty: {recs.get('task_difficulty', 'maintain')}\n"
        f"Calories: {recs.get('calorie_adjustment', 'maintain')}\n\n---\n"
    )
    path.write_text(existing + block, encoding="utf-8")


def _append_adaptation_log(analysis: dict) -> None:
    path = config.MEMORY_DIR / "adaptation_log.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    recs = analysis.get("recommendations", {})
    entry = (
        f"\n## {date.today().isoformat()}\n\n"
        f"{analysis.get('summary', 'No summary.')}\n\n"
        f"Missed patterns: {', '.join(analysis.get('missed_task_patterns', ['none']))}\n"
        f"Task difficulty → {recs.get('task_difficulty', 'maintain')}\n\n---\n"
    )
    path.write_text(existing + entry, encoding="utf-8")


# ── Nutrition estimator ───────────────────────────────────────────────────────
async def estimate_nutrition(food_description: str) -> dict:
    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=100,
        system="You are a nutritionist. Return only JSON.",
        messages=[{
            "role": "user",
            "content": (
                f'Estimate nutrition for: "{food_description}"\n'
                'Return ONLY: {"protein_g": <number>, "calories": <number>}\n'
                "Use standard portions. Give a reasonable middle estimate."
            ),
        }],
    )
    try:
        data = json.loads(_strip_json(resp.content[0].text))
        return {"protein_g": float(data.get("protein_g", 0)), "calories": int(data.get("calories", 0))}
    except (json.JSONDecodeError, ValueError):
        return {"protein_g": 0.0, "calories": 0}


# ── Journal prompt ────────────────────────────────────────────────────────────
async def generate_journal_prompt() -> str:
    prompt_template = _load_prompt("journaling_prompt")
    checkin = await db.get_checkin(date.today().isoformat()) or {}

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=200,
        system=_build_system_prompt(),
        messages=[{
            "role": "user",
            "content": (
                f"{prompt_template}\n\nToday's energy: {checkin.get('energy', '?')}/10.\n"
                "Generate one focused journaling prompt. Max 60 words."
            ),
        }],
    )
    return resp.content[0].text.strip()
