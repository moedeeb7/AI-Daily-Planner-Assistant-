"""
SQLite database layer — all schema creation, inserts, and queries live here.
Uses aiosqlite for async access compatible with the python-telegram-bot event loop.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from config import DB_PATH

# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS daily_checkins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL UNIQUE,
    energy      INTEGER,
    mood        INTEGER,
    appetite    INTEGER,
    sleep_hrs   REAL,
    notes       TEXT,
    created_at  TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    date           TEXT    NOT NULL,
    tier           TEXT    NOT NULL,
    category       TEXT    NOT NULL,
    description    TEXT    NOT NULL,
    scheduled_time TEXT,
    completed      INTEGER DEFAULT 0,
    skipped        INTEGER DEFAULT 0,
    rescheduled    INTEGER DEFAULT 0,
    energy_after   INTEGER,
    effort         INTEGER,
    benefit        INTEGER,
    notes          TEXT,
    created_at     TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meal_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL,
    time        TEXT,
    description TEXT    NOT NULL,
    protein_g   REAL    DEFAULT 0,
    calories    INTEGER DEFAULT 0,
    raw_message TEXT,
    created_at  TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS weight_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL,
    weight_kg  REAL    NOT NULL,
    notes      TEXT,
    created_at TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workout_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL,
    completed  INTEGER DEFAULT 0,
    duration_m INTEGER,
    exercises  TEXT,
    notes      TEXT,
    created_at TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS job_applications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL,
    company    TEXT,
    position   TEXT,
    platform   TEXT,
    status     TEXT    DEFAULT 'applied',
    notes      TEXT,
    created_at TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ai_income_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL,
    task_type   TEXT,
    description TEXT,
    completed   INTEGER DEFAULT 0,
    notes       TEXT,
    created_at  TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    timestamp   TEXT    DEFAULT (datetime('now')),
    direction   TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    msg_type    TEXT,
    metadata    TEXT
);

CREATE TABLE IF NOT EXISTS follow_ups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER REFERENCES tasks(id),
    scheduled_at TEXT    NOT NULL,
    sent         INTEGER DEFAULT 0,
    responded    INTEGER DEFAULT 0,
    context      TEXT,
    created_at   TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS behavior_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT    NOT NULL,
    analysis   TEXT    NOT NULL,
    created_at TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_date       ON tasks(date);
CREATE INDEX IF NOT EXISTS idx_meals_date       ON meal_logs(date);
CREATE INDEX IF NOT EXISTS idx_weight_date      ON weight_logs(date);
CREATE INDEX IF NOT EXISTS idx_conversations_ts ON conversations(timestamp);
"""


def init_db_sync() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


# ── Async helpers ─────────────────────────────────────────────────────────────
async def _fetchone(query: str, params: tuple = ()) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _fetchall(query: str, params: tuple = ()) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def _execute(query: str, params: tuple = ()) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as cur:
            await db.commit()
            return cur.lastrowid


# ── Daily check-in ────────────────────────────────────────────────────────────
async def upsert_checkin(
    date_str: str,
    energy: Optional[int] = None,
    mood: Optional[int] = None,
    appetite: Optional[int] = None,
    sleep_hrs: Optional[float] = None,
    notes: Optional[str] = None,
) -> None:
    # Single atomic upsert — avoids two round-trips
    await _execute(
        """INSERT INTO daily_checkins(date, energy, mood, appetite, sleep_hrs, notes)
           VALUES(?, ?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             energy    = COALESCE(excluded.energy,    energy),
             mood      = COALESCE(excluded.mood,      mood),
             appetite  = COALESCE(excluded.appetite,  appetite),
             sleep_hrs = COALESCE(excluded.sleep_hrs, sleep_hrs),
             notes     = COALESCE(excluded.notes,     notes)""",
        (date_str, energy, mood, appetite, sleep_hrs, notes),
    )


async def get_checkin(date_str: str) -> Optional[dict]:
    return await _fetchone("SELECT * FROM daily_checkins WHERE date = ?", (date_str,))


# ── Tasks ─────────────────────────────────────────────────────────────────────
async def create_task(
    date_str: str,
    tier: str,
    category: str,
    description: str,
    scheduled_time: Optional[str] = None,
) -> int:
    return await _execute(
        """INSERT INTO tasks(date, tier, category, description, scheduled_time)
           VALUES(?, ?, ?, ?, ?)""",
        (date_str, tier, category, description, scheduled_time),
    )


async def get_tasks_for_date(date_str: str) -> list[dict]:
    return await _fetchall(
        "SELECT * FROM tasks WHERE date = ? ORDER BY tier, scheduled_time",
        (date_str,),
    )


async def complete_task(
    task_id: int,
    energy_after: Optional[int] = None,
    effort: Optional[int] = None,
    benefit: Optional[int] = None,
    notes: Optional[str] = None,
) -> None:
    await _execute(
        """UPDATE tasks
           SET completed=1,
               energy_after = COALESCE(?, energy_after),
               effort       = COALESCE(?, effort),
               benefit      = COALESCE(?, benefit),
               notes        = COALESCE(?, notes)
           WHERE id = ?""",
        (energy_after, effort, benefit, notes, task_id),
    )


async def skip_task(task_id: int) -> None:
    await _execute("UPDATE tasks SET skipped=1 WHERE id=?", (task_id,))


async def reschedule_task(task_id: int, new_time: str) -> None:
    await _execute(
        "UPDATE tasks SET scheduled_time=?, rescheduled=rescheduled+1 WHERE id=?",
        (new_time, task_id),
    )


async def get_incomplete_gold_tasks(date_str: str) -> list[dict]:
    return await _fetchall(
        "SELECT * FROM tasks WHERE date=? AND tier='gold' AND completed=0 AND skipped=0",
        (date_str,),
    )


# ── Meals ─────────────────────────────────────────────────────────────────────
async def log_meal(
    date_str: str,
    description: str,
    protein_g: float = 0,
    calories: int = 0,
    raw_message: Optional[str] = None,
) -> int:
    time_str = datetime.now().strftime("%H:%M")
    return await _execute(
        """INSERT INTO meal_logs(date, time, description, protein_g, calories, raw_message)
           VALUES(?, ?, ?, ?, ?, ?)""",
        (date_str, time_str, description, protein_g, calories, raw_message),
    )


async def get_daily_nutrition(date_str: str) -> dict:
    rows = await _fetchall(
        "SELECT protein_g, calories FROM meal_logs WHERE date=?", (date_str,)
    )
    return {
        "protein_g": sum(r["protein_g"] for r in rows),
        "calories": sum(r["calories"] for r in rows),
        "meal_count": len(rows),
    }


async def get_meals_for_date(date_str: str) -> list[dict]:
    return await _fetchall("SELECT * FROM meal_logs WHERE date=? ORDER BY time", (date_str,))


# ── Weight ────────────────────────────────────────────────────────────────────
async def log_weight(date_str: str, weight_kg: float, notes: Optional[str] = None) -> int:
    return await _execute(
        "INSERT INTO weight_logs(date, weight_kg, notes) VALUES(?, ?, ?)",
        (date_str, weight_kg, notes),
    )


async def get_weight_history(days: int = 14) -> list[dict]:
    return await _fetchall(
        """SELECT date, AVG(weight_kg) AS weight_kg
           FROM weight_logs
           GROUP BY date
           ORDER BY date DESC
           LIMIT ?""",
        (days,),
    )


async def get_latest_weight() -> Optional[dict]:
    return await _fetchone(
        "SELECT * FROM weight_logs ORDER BY date DESC, id DESC LIMIT 1"
    )


# ── Workouts ──────────────────────────────────────────────────────────────────
async def log_workout(
    date_str: str,
    completed: bool,
    duration_m: Optional[int] = None,
    exercises: Optional[list] = None,
    notes: Optional[str] = None,
) -> int:
    exercises_json = json.dumps(exercises) if exercises else None
    return await _execute(
        """INSERT INTO workout_logs(date, completed, duration_m, exercises, notes)
           VALUES(?, ?, ?, ?, ?)""",
        (date_str, int(completed), duration_m, exercises_json, notes),
    )


async def get_workout_streak() -> int:
    # Group by date so multiple logs on the same day don't break the streak
    rows = await _fetchall(
        """SELECT date, MAX(completed) AS completed
           FROM workout_logs
           GROUP BY date
           ORDER BY date DESC
           LIMIT 30"""
    )
    streak = 0
    for r in rows:
        if r["completed"]:
            streak += 1
        else:
            break
    return streak


# ── Job applications ──────────────────────────────────────────────────────────
async def log_job_application(
    date_str: str,
    company: Optional[str],
    position: Optional[str],
    platform: Optional[str] = None,
    notes: Optional[str] = None,
) -> int:
    return await _execute(
        """INSERT INTO job_applications(date, company, position, platform, notes)
           VALUES(?, ?, ?, ?, ?)""",
        (date_str, company, position, platform, notes),
    )


async def get_job_stats(days: int = 7) -> dict:
    rows = await _fetchall(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status='interview' THEN 1 ELSE 0 END) AS interviews
           FROM job_applications
           WHERE date >= date('now', ?)""",
        (f"-{days} days",),
    )
    return rows[0] if rows else {"total": 0, "interviews": 0}


# ── AI income ─────────────────────────────────────────────────────────────────
async def log_ai_income_task(
    date_str: str,
    task_type: str,
    description: str,
    completed: bool = False,
    notes: Optional[str] = None,
) -> int:
    return await _execute(
        """INSERT INTO ai_income_logs(date, task_type, description, completed, notes)
           VALUES(?, ?, ?, ?, ?)""",
        (date_str, task_type, description, int(completed), notes),
    )


# ── Conversations ─────────────────────────────────────────────────────────────
async def save_message(
    direction: str,
    content: str,
    msg_type: Optional[str] = None,
    metadata: Optional[dict] = None,
    telegram_id: Optional[int] = None,
) -> int:
    meta_json = json.dumps(metadata) if metadata else None
    return await _execute(
        """INSERT INTO conversations(telegram_id, direction, content, msg_type, metadata)
           VALUES(?, ?, ?, ?, ?)""",
        (telegram_id, direction, content, msg_type, meta_json),
    )


async def get_recent_conversation(limit: int = 20) -> list[dict]:
    return await _fetchall(
        """SELECT direction, content, msg_type, timestamp
           FROM conversations
           ORDER BY timestamp DESC
           LIMIT ?""",
        (limit,),
    )


# ── Follow-ups ────────────────────────────────────────────────────────────────
async def create_followup(
    task_id: Optional[int], scheduled_at: str, context: Optional[str] = None
) -> int:
    return await _execute(
        "INSERT INTO follow_ups(task_id, scheduled_at, context) VALUES(?, ?, ?)",
        (task_id, scheduled_at, context),
    )


async def get_pending_followups() -> list[dict]:
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    return await _fetchall(
        "SELECT * FROM follow_ups WHERE sent=0 AND scheduled_at <= ?",
        (now,),
    )


async def mark_followup_sent(followup_id: int) -> None:
    await _execute("UPDATE follow_ups SET sent=1 WHERE id=?", (followup_id,))


async def mark_followup_responded(followup_id: int) -> None:
    await _execute("UPDATE follow_ups SET responded=1 WHERE id=?", (followup_id,))


# ── Behavior snapshots ────────────────────────────────────────────────────────
async def save_behavior_snapshot(week_start: str, analysis: dict) -> int:
    return await _execute(
        "INSERT INTO behavior_snapshots(week_start, analysis) VALUES(?, ?)",
        (week_start, json.dumps(analysis)),
    )


async def get_last_behavior_snapshot() -> Optional[dict]:
    row = await _fetchone(
        "SELECT * FROM behavior_snapshots ORDER BY created_at DESC LIMIT 1"
    )
    if row:
        row["analysis"] = json.loads(row["analysis"])
    return row


# ── Analytics helpers ─────────────────────────────────────────────────────────
async def get_task_completion_rate(days: int = 7) -> dict:
    rows = await _fetchall(
        """SELECT tier, COUNT(*) AS total, SUM(completed) AS done
           FROM tasks
           WHERE date >= date('now', ?)
           GROUP BY tier""",
        (f"-{days} days",),
    )
    return {r["tier"]: {"total": r["total"], "done": r["done"]} for r in rows}


async def get_energy_trend(days: int = 7) -> list[dict]:
    return await _fetchall(
        """SELECT date, energy, mood FROM daily_checkins
           WHERE date >= date('now', ?)
           ORDER BY date""",
        (f"-{days} days",),
    )


async def get_weekly_summary(days: int = 7) -> dict:
    nutrition = await _fetchone(
        """SELECT AVG(protein_g) AS avg_protein, AVG(calories) AS avg_calories
           FROM (
               SELECT date, SUM(protein_g) AS protein_g, SUM(calories) AS calories
               FROM meal_logs WHERE date >= date('now', ?)
               GROUP BY date
           )""",
        (f"-{days} days",),
    )
    completion = await get_task_completion_rate(days)
    job_stats = await get_job_stats(days)
    weight_hist = await get_weight_history(days)
    workout_streak = await get_workout_streak()

    return {
        "nutrition": nutrition or {},
        "task_completion": completion,
        "job_stats": job_stats,
        "weight_history": weight_hist,
        "workout_streak": workout_streak,
    }
