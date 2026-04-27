"""
Google Calendar integration — read existing schedule, create events for tasks,
and adjust dynamically.

Authentication: OAuth 2.0 with token caching (google_token.json).
First run requires browser flow — after that it's automatic.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config

logger = logging.getLogger(__name__)

# Duration defaults per category (minutes)
CATEGORY_DURATION: dict[str, int] = {
    "gym": 75,
    "diet": 20,
    "job": 60,
    "ai_income": 90,
    "habit": 15,
    "other": 30,
}

# Color IDs per task tier (Google Calendar color IDs 1-11)
TIER_COLOR: dict[str, str] = {
    "gold": "5",    # Banana yellow
    "silver": "7",  # Peacock blue
    "bronze": "8",  # Graphite
}


def _get_credentials() -> Optional[Credentials]:
    """Load or refresh OAuth credentials. Returns None on failure."""
    creds = None

    if config.GOOGLE_TOKEN_FILE and __import__("os").path.exists(config.GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(config.GOOGLE_TOKEN_FILE, config.GOOGLE_SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except Exception as exc:
            logger.warning("Token refresh failed: %s", exc)

    # Need fresh auth — only works if a browser is available
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            config.GOOGLE_CREDENTIALS_FILE, config.GOOGLE_SCOPES
        )
        creds = flow.run_local_server(port=0)
        _save_token(creds)
        return creds
    except Exception as exc:
        logger.error("Google OAuth flow failed: %s", exc)
        return None


def _save_token(creds: Credentials) -> None:
    import json
    with open(config.GOOGLE_TOKEN_FILE, "w") as f:
        f.write(creds.to_json())


def _build_service():
    creds = _get_credentials()
    if creds is None:
        raise RuntimeError("Google Calendar: no valid credentials available.")
    return build("calendar", "v3", credentials=creds)


# ── Core helpers ──────────────────────────────────────────────────────────────
def _make_datetime(date_str: str, time_str: str, tz: ZoneInfo) -> datetime:
    """Parse a YYYY-MM-DD + HH:MM pair into a tz-aware datetime."""
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=tz)


def _event_body(
    summary: str,
    start: datetime,
    end: datetime,
    description: str = "",
    color_id: Optional[str] = None,
) -> dict:
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": config.TIMEZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": config.TIMEZONE},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 10}],
        },
    }
    if color_id:
        body["colorId"] = color_id
    return body


# ── Public API ────────────────────────────────────────────────────────────────
async def get_todays_events() -> list[dict]:
    """Return all calendar events for today, sorted by start time."""
    tz = ZoneInfo(config.TIMEZONE)
    today = date.today()
    start_of_day = datetime(today.year, today.month, today.day, 0, 0, tzinfo=tz)
    end_of_day = start_of_day + timedelta(days=1)

    try:
        service = _build_service()
        result = (
            service.events()
            .list(
                calendarId=config.GOOGLE_CALENDAR_ID,
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return result.get("items", [])
    except HttpError as exc:
        logger.error("Calendar fetch failed: %s", exc)
        return []
    except RuntimeError as exc:
        logger.warning("Calendar not configured: %s", exc)
        return []


async def create_event(
    summary: str,
    date_str: str,
    start_time: str,
    duration_minutes: int,
    description: str = "",
    color_id: Optional[str] = None,
) -> Optional[str]:
    """Create a single calendar event. Returns the event ID or None."""
    tz = ZoneInfo(config.TIMEZONE)
    start = _make_datetime(date_str, start_time, tz)
    end = start + timedelta(minutes=duration_minutes)

    try:
        service = _build_service()
        event = (
            service.events()
            .insert(
                calendarId=config.GOOGLE_CALENDAR_ID,
                body=_event_body(summary, start, end, description, color_id),
            )
            .execute()
        )
        logger.info("Calendar event created: %s (%s)", summary, event["id"])
        return event["id"]
    except HttpError as exc:
        logger.error("Event creation failed: %s", exc)
        return None
    except RuntimeError as exc:
        logger.warning("Calendar not configured: %s", exc)
        return None


async def sync_tasks_to_calendar(tasks: list[dict]) -> None:
    """
    Create calendar events for a list of task dicts.
    Each task must have: description, tier, category, scheduled_time.
    """
    today_str = date.today().isoformat()

    for task in tasks:
        scheduled_time = task.get("scheduled_time")
        if not scheduled_time:
            continue  # Only create events for time-scheduled tasks

        category = task.get("category", "other")
        tier = task.get("tier", "bronze")
        duration = CATEGORY_DURATION.get(category, 30)
        color_id = TIER_COLOR.get(tier)

        summary = f"[{tier.upper()}] {task['description']}"
        description = task.get("rationale", "")

        await create_event(
            summary=summary,
            date_str=today_str,
            start_time=scheduled_time,
            duration_minutes=duration,
            description=description,
            color_id=color_id,
        )


async def create_recurring_events() -> None:
    """
    Create standard weekly events:
    - Morning workout block (Mon/Wed/Fri 07:00)
    - Job search block (Mon–Fri 10:00)
    - AI income work (Mon–Fri 14:00)
    - Evening review (daily 21:00)
    """
    today_str = date.today().isoformat()
    tz = ZoneInfo(config.TIMEZONE)
    today = date.today()
    weekday = today.weekday()  # 0=Mon

    events_to_create = []

    # Gym days: Mon(0), Wed(2), Fri(4)
    if weekday in (0, 2, 4):
        events_to_create.append({
            "summary": "[GOLD] Morning Gym",
            "start_time": "07:00",
            "duration": 75,
            "color_id": "5",
        })

    # Job search: Mon–Fri
    if weekday < 5:
        events_to_create.append({
            "summary": "[SILVER] Job Search Block",
            "start_time": "10:00",
            "duration": 60,
            "color_id": "7",
        })
        events_to_create.append({
            "summary": "[SILVER] AI Income Work",
            "start_time": "14:00",
            "duration": 90,
            "color_id": "7",
        })

    # Evening review: every day
    events_to_create.append({
        "summary": "[BRONZE] Evening Review",
        "start_time": "21:00",
        "duration": 20,
        "color_id": "8",
    })

    for ev in events_to_create:
        await create_event(
            summary=ev["summary"],
            date_str=today_str,
            start_time=ev["start_time"],
            duration_minutes=ev["duration"],
            color_id=ev.get("color_id"),
        )


async def reschedule_event(event_id: str, new_start_time: str) -> bool:
    """Move an existing event to a new start time (same day, same duration)."""
    tz = ZoneInfo(config.TIMEZONE)
    today_str = date.today().isoformat()

    try:
        service = _build_service()
        event = service.events().get(
            calendarId=config.GOOGLE_CALENDAR_ID, eventId=event_id
        ).execute()

        old_start = datetime.fromisoformat(event["start"]["dateTime"])
        old_end = datetime.fromisoformat(event["end"]["dateTime"])
        duration = old_end - old_start

        new_start = _make_datetime(today_str, new_start_time, tz)
        new_end = new_start + duration

        event["start"] = {"dateTime": new_start.isoformat(), "timeZone": config.TIMEZONE}
        event["end"] = {"dateTime": new_end.isoformat(), "timeZone": config.TIMEZONE}

        service.events().update(
            calendarId=config.GOOGLE_CALENDAR_ID, eventId=event_id, body=event
        ).execute()
        return True
    except (HttpError, RuntimeError) as exc:
        logger.error("Reschedule failed: %s", exc)
        return False


async def delete_event(event_id: str) -> bool:
    try:
        service = _build_service()
        service.events().delete(
            calendarId=config.GOOGLE_CALENDAR_ID, eventId=event_id
        ).execute()
        return True
    except (HttpError, RuntimeError) as exc:
        logger.error("Event deletion failed: %s", exc)
        return False
