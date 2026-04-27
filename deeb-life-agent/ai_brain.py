"""
AI reasoning engine — all Claude API calls go through here.

Every public function returns a plain string (the agent's reply or plan).
The caller is responsible for sending that string to Telegram.
"""
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import anthropic

import config
import database as db

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

# ── Memory loader ─────────────────────────────────────────────────────────────
def _load_memory() -> str:
    parts = []
    for md_file in sorted(config.MEMORY_DIR.glob("*.md")):
        text = md_file.read_text(encoding="utf-8").strip()
        if text:
            parts.append(f"### {md_file.stem.replace('_', ' ').title()}\n{text}")
    return "\n\n".join(parts)


def _load_prompt(name: str) -> str:
    path = config.PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def _build_system_prompt() -> str:
    memory = _load_memory()
    return f"""You are Deeb's personal AI Life Operating System — a direct, structured, action-focused agent.

Your role covers: daily assistant, life coach, schedule manager, fitness/weight-gain coach, job search manager, and AI income strategist.

## Core rules
- Always give: (1) what matters now, (2) the next concrete action, (3) why it matters.
- Never give generic advice. Everything must be grounded in Deeb's real situation.
- Tone: direct, practical, structured. Supportive but not soft. Zero fluff.
- If Deeb fails at something: recover the day — do NOT reset everything.
- Keep responses under 250 words unless generating a full daily plan.
- Use short paragraphs or bullet points. Never use walls of text.
- Always end with a single, specific "→ Action:" line.

## Deeb's permanent memory
{memory}

## Current date
{date.today().isoformat()} ({datetime.now().strftime('%A')})
"""


# ── Message classifier ────────────────────────────────────────────────────────
VALID_MSG_TYPES = {
    "weight_log", "meal_log", "workout_log", "job_task",
    "ai_task", "journal", "mood_energy", "general",
    "checkin_response", "task_completion", "skip_report",
}


async def classify_message(text: str) -> dict:
    """
    Returns {type, structured_data, summary} where structured_data is a dict
    with extracted fields (e.g., weight_kg, protein_g, calories, etc.).
    """
    prompt = f"""Classify this message from Deeb and extract structured data.

Message: "{text}"

Return ONLY valid JSON (no markdown) with this shape:
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
    "sleep_hrs": null
  }}
}}

Fill only the fields that are relevant. Use null for everything else.
Only return JSON — no explanation."""

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=512,
        system="You are a JSON extraction engine. Return only valid JSON, nothing else.",
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    # Strip markdown code blocks if present
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"type": "general", "summary": text[:100], "structured_data": {}}


# ── Morning check-in ──────────────────────────────────────────────────────────
async def generate_morning_checkin() -> str:
    prompt_template = _load_prompt("morning_checkin")
    today_str = date.today().isoformat()

    weekly_summary = await db.get_weekly_summary(7)
    latest_weight = await db.get_latest_weight()

    context = f"""
Today: {today_str} ({datetime.now().strftime('%A')})
Latest weight: {latest_weight['weight_kg'] if latest_weight else 'unknown'} kg
7-day task completion: {json.dumps(weekly_summary.get('task_completion', {}), indent=2)}
Workout streak: {weekly_summary.get('workout_streak', 0)} days
"""

    messages = [
        {
            "role": "user",
            "content": f"{prompt_template}\n\nContext:\n{context}\n\nGenerate today's morning check-in message. Ask energy (1-10), mood (1-10), appetite (1-10), and sleep hours. Keep it concise, direct, and motivating. Max 120 words.",
        }
    ]

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=300,
        system=_build_system_prompt(),
        messages=messages,
    )
    return resp.content[0].text.strip()


# ── Daily plan generator ──────────────────────────────────────────────────────
async def generate_daily_plan(
    energy: int, mood: int, appetite: int, sleep_hrs: float
) -> dict:
    """
    Returns a structured plan: {tasks: [...], schedule: {...}, notes: str}
    Each task: {tier, category, description, scheduled_time, rationale}
    """
    today_str = date.today().isoformat()
    day_name = datetime.now().strftime("%A")
    nutrition = await db.get_daily_nutrition(today_str)
    job_stats = await db.get_job_stats(7)
    completion = await db.get_task_completion_rate(7)

    prompt = f"""
Today: {today_str} ({day_name})
Deeb's morning stats — Energy: {energy}/10, Mood: {mood}/10, Appetite: {appetite}/10, Sleep: {sleep_hrs}h

Weekly context:
- Job applications (7d): {job_stats['total']}
- Task completion: {json.dumps(completion, indent=2)}

Energy rule: {'High energy → deep work blocks' if energy >= 7 else 'Medium energy → structured tasks' if energy >= 5 else 'Low energy → recovery + light tasks only'}

Generate a realistic daily plan as JSON with this exact shape:
{{
  "tasks": [
    {{
      "tier": "gold|silver|bronze",
      "category": "gym|diet|job|ai_income|habit|other",
      "description": "...",
      "scheduled_time": "HH:MM",
      "rationale": "one line"
    }}
  ],
  "energy_note": "brief note on how today's energy shapes the plan",
  "recovery_note": "what to do if energy crashes mid-day"
}}

Rules:
- Exactly {config.DAILY_GOLD_REQUIRED} gold task(s), {config.DAILY_SILVER_REQUIRED} silver, {config.DAILY_BRONZE_REQUIRED} bronze
- If energy < 5: make gold task lighter (e.g., 30-min walk instead of full gym)
- If mood < 5: reduce cognitive load tasks, add one recovery habit
- If sleep < 6: schedule a rest block, push deep work to afternoon
- Space tasks realistically — no impossible stacking
- Return ONLY the JSON object, no markdown, no explanation
"""

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "tasks": [],
            "energy_note": "Plan generation failed — defaulting to core habits.",
            "recovery_note": "Focus on gym, 1 job application, protein intake.",
        }


# ── Context-aware response ────────────────────────────────────────────────────
async def generate_response(user_message: str, msg_type: str, metadata: dict) -> str:
    """
    Generate a coaching response to any inbound message from Deeb.
    """
    today_str = date.today().isoformat()

    # Build a lean context snapshot
    checkin = await db.get_checkin(today_str) or {}
    tasks = await db.get_tasks_for_date(today_str)
    nutrition = await db.get_daily_nutrition(today_str)
    incomplete_gold = await db.get_incomplete_gold_tasks(today_str)

    completed_tasks = [t for t in tasks if t["completed"]]
    pending_tasks = [t for t in tasks if not t["completed"] and not t["skipped"]]

    context = f"""
Today's check-in: energy={checkin.get('energy','?')}, mood={checkin.get('mood','?')}
Nutrition so far: {nutrition['protein_g']}g protein, {nutrition['calories']} kcal
Tasks completed: {len(completed_tasks)}/{len(tasks)}
Pending gold tasks: {[t['description'] for t in incomplete_gold]}
Message type classified as: {msg_type}
"""

    recent_conv = await db.get_recent_conversation(6)
    history = []
    for msg in reversed(recent_conv):
        role = "user" if msg["direction"] == "inbound" else "assistant"
        history.append({"role": role, "content": msg["content"]})

    # Add the current message
    history.append({"role": "user", "content": f"[Context]{context}\n\nDeeb says: {user_message}"})

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
    energy = checkin.get("energy", 5)

    prompt = f"""Generate a pre-task reminder for Deeb.

Task: {task['description']} (tier: {task['tier']}, category: {task['category']})
Scheduled: {task.get('scheduled_time', 'now')}
Deeb's current energy: {energy}/10

Keep it under 80 words. Be direct. Ask one readiness question. End with '→ Action:' line."""

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=200,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


# ── Post-task check-in ────────────────────────────────────────────────────────
async def generate_post_task_checkin(task: dict) -> str:
    prompt = f"""Generate a post-task check-in for Deeb.

Task just completed (or attempted): {task['description']}
Category: {task['category']}

Ask: 1) Did you complete it? 2) Energy level after (1-10)? 3) Effort needed (1-10)?
Max 60 words. Direct tone. No fluff."""

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
    tasks = await db.get_tasks_for_date(today_str)
    nutrition = await db.get_daily_nutrition(today_str)
    checkin = await db.get_checkin(today_str) or {}

    completed = [t for t in tasks if t["completed"]]
    skipped = [t for t in tasks if t["skipped"]]
    missed = [t for t in tasks if not t["completed"] and not t["skipped"]]

    context = f"""
Date: {today_str}
Morning energy: {checkin.get('energy', '?')}/10, mood: {checkin.get('mood', '?')}/10

Completed ({len(completed)}): {[t['description'] for t in completed]}
Skipped ({len(skipped)}): {[t['description'] for t in skipped]}
Missed ({len(missed)}): {[t['description'] for t in missed]}

Nutrition: {nutrition['protein_g']:.0f}g protein, {nutrition['calories']} kcal
Protein target: {config.MIN_PROTEIN_G}g — {'MET ✓' if nutrition['protein_g'] >= config.MIN_PROTEIN_G else 'MISSED ✗'}
"""

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
    simplify = attempt > 1
    prompt = f"""Generate a follow-up message for Deeb.

Context: {context_note}
This is follow-up attempt #{attempt}.

{'Since there has been no response, simplify the ask — give one tiny action.' if simplify else 'Be direct and brief.'}
Max 60 words. Always end with a single question or single action."""

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
        messages=[
            {
                "role": "user",
                "content": f"{prompt_template}\n\nWeekly data:\n{context}\n\nGenerate the weekly report. Max 400 words. Use sections: Wins, Misses, Pattern Spotted, Next Week Focus.",
            }
        ],
    )
    return resp.content[0].text.strip()


# ── Adaptation engine ─────────────────────────────────────────────────────────
async def run_adaptation_engine() -> dict:
    """
    Analyzes last 7 days of data, updates behavior_patterns.md and adaptation_log.md,
    returns a dict with the analysis.
    """
    summary = await db.get_weekly_summary(7)
    energy_trend = await db.get_energy_trend(7)
    task_rates = await db.get_task_completion_rate(7)
    weight_hist = await db.get_weight_history(7)
    prompt_template = _load_prompt("adaptation_prompt")

    context = f"""
Task completion rates: {json.dumps(task_rates, indent=2)}
Energy trend (7d): {json.dumps(energy_trend, indent=2, default=str)}
Weight history: {json.dumps(weight_hist, indent=2, default=str)}
Job stats: {json.dumps(summary.get('job_stats', {}), indent=2)}
Nutrition averages: {json.dumps(summary.get('nutrition', {}), indent=2)}
Workout streak: {summary.get('workout_streak', 0)}
"""

    analysis_prompt = f"""{prompt_template}

Data from last 7 days:
{context}

Analyze and return ONLY valid JSON with this structure:
{{
  "missed_task_patterns": ["pattern1", "pattern2"],
  "best_performance_times": ["morning", "evening"],
  "energy_trend": "improving|declining|stable",
  "successful_habits": ["habit1"],
  "recommendations": {{
    "schedule_adjustments": ["..."],
    "task_difficulty": "increase|decrease|maintain",
    "habit_frequency": {{"gym": "daily|5x|3x", "journaling": "daily|3x|weekly"}},
    "calorie_adjustment": "increase|maintain|decrease",
    "protein_adjustment": "increase|maintain"
  }},
  "summary": "2-sentence plain-English summary of the week"
}}"""

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": analysis_prompt}],
    )
    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE)

    try:
        analysis = json.loads(raw)
    except json.JSONDecodeError:
        analysis = {"summary": "Adaptation engine parse error — raw data preserved.", "raw": raw}

    # Write to markdown files
    _update_behavior_patterns(analysis)
    _append_adaptation_log(analysis)

    # Persist to DB
    week_start = date.today().isoformat()
    await db.save_behavior_snapshot(week_start, analysis)

    return analysis


def _update_behavior_patterns(analysis: dict) -> None:
    path = config.MEMORY_DIR / "behavior_patterns.md"
    today = date.today().isoformat()
    content = path.read_text(encoding="utf-8") if path.exists() else ""

    update_block = f"""
## Update: {today}

**Energy trend:** {analysis.get('energy_trend', 'unknown')}
**Best performance times:** {', '.join(analysis.get('best_performance_times', []))}
**Successful habits:** {', '.join(analysis.get('successful_habits', []))}
**Missed task patterns:** {', '.join(analysis.get('missed_task_patterns', []))}

### Recommendations
- Schedule: {'; '.join(analysis.get('recommendations', {}).get('schedule_adjustments', []))}
- Task difficulty: {analysis.get('recommendations', {}).get('task_difficulty', 'maintain')}
- Calorie adjustment: {analysis.get('recommendations', {}).get('calorie_adjustment', 'maintain')}

---
"""
    path.write_text(content + update_block, encoding="utf-8")


def _append_adaptation_log(analysis: dict) -> None:
    path = config.MEMORY_DIR / "adaptation_log.md"
    today = date.today().isoformat()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    log_entry = f"""
## {today}

{analysis.get('summary', 'No summary available.')}

**Missed patterns:** {', '.join(analysis.get('missed_task_patterns', ['none']))}
**Recs applied:** Task difficulty → {analysis.get('recommendations', {}).get('task_difficulty', 'maintain')}

---
"""
    path.write_text(existing + log_entry, encoding="utf-8")


# ── Meal nutrition estimator ──────────────────────────────────────────────────
async def estimate_nutrition(food_description: str) -> dict:
    """Returns {protein_g, calories} estimates for a food description."""
    prompt = f"""Estimate nutritional content for: "{food_description}"

Return ONLY JSON:
{{"protein_g": <number>, "calories": <number>}}

Base estimates on standard portions. If unsure, give a reasonable middle estimate."""

    resp = _client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=100,
        system="You are a nutritionist. Return only JSON.",
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE)
    try:
        data = json.loads(raw)
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
        messages=[
            {
                "role": "user",
                "content": f"{prompt_template}\n\nToday's energy: {checkin.get('energy', '?')}/10. Generate a single focused journaling prompt. Max 60 words.",
            }
        ],
    )
    return resp.content[0].text.strip()
