"""
Google Calendar integration.

Authentication: OAuth 2.0 with token caching (google_token.json).
First run opens a browser for auth — subsequent runs are automatic.
"""
import json
import logging
import os
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

CATEGORY_DURATION: dict[str, int] = {
    "gym": 75, "diet": 20, "job": 60,
    "ai_income": 90, "habit": 15, "other": 30,
}

TIER_COLOR: dict[str, str] = {
    "gold": "5",    # Banana yellow
    "silver": "7",  # Peacock blue
    "bronze": "8",  # Graphite
}


# ── Auth ──────────────────────────────────────────────────────────────────────
def _get_credentials() -> Optional[Credentials]:
    creds = None

    if os.path.exists(config.GOOGLE_TOKEN_FILE):
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
    with open(config.GOOGLE_TOKEN_FILE, "w") as f:
        f.write(creds.to_json())


def _build_service():
    creds = _get_credentials()
    if creds is None:
        raise RuntimeError("Google Calendar: no valid credentials.")
    return build("calendar", "v3", credentials=creds)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _make_datetime(date_str: str, time_str: str, tz: ZoneInfo) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)


def _event_body(
    summary: str, start: datetime, end: datetime,
    description: str = "", color_id: Optional[str] = None,
) -> dict:
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start.isoformat(), "timeZone": config.TIMEZONE},
        "end":   {"dateTime": end.isoformat(),   "timeZone": config.TIMEZONE},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}]},
    }
    if color_id:
        body["colorId"] = color_id
    return body


# ── Public API ────────────────────────────────────────────────────────────────
async def get_todays_events() -> list[dict]:
    tz = ZoneInfo(config.TIMEZONE)
    today = date.today()
    start = datetime(today.year, today.month, today.day, tzinfo=tz)
    end = start + timedelta(days=1)

    try:
        service = _build_service()
        result = (
            service.events()
            .list(calendarId=config.GOOGLE_CALENDAR_ID,
                  timeMin=start.isoformat(), timeMax=end.isoformat(),
                  singleEvents=True, orderBy="startTime")
            .execute()
        )
        return result.get("items", [])
    except (HttpError, RuntimeError) as exc:
        logger.error("Calendar fetch failed: %s", exc)
        return []


async def create_event(
    summary: str, date_str: str, start_time: str, duration_minutes: int,
    description: str = "", color_id: Optional[str] = None,
) -> Optional[str]:
    tz = ZoneInfo(config.TIMEZONE)
    start = _make_datetime(date_str, start_time, tz)
    end = start + timedelta(minutes=duration_minutes)

    try:
        service = _build_service()
        event = (
            service.events()
            .insert(calendarId=config.GOOGLE_CALENDAR_ID,
                    body=_event_body(summary, start, end, description, color_id))
            .execute()
        )
        logger.info("Calendar event created: %s (%s)", summary, event["id"])
        return event["id"]
    except (HttpError, RuntimeError) as exc:
        logger.error("Event creation failed: %s", exc)
        return None


async def sync_tasks_to_calendar(tasks: list[dict]) -> None:
    today_str = date.today().isoformat()
    for task in tasks:
        if not task.get("scheduled_time"):
            continue
        await create_event(
            summary=f"[{task.get('tier','?').upper()}] {task['description']}",
            date_str=today_str,
            start_time=task["scheduled_time"],
            duration_minutes=CATEGORY_DURATION.get(task.get("category", "other"), 30),
            description=task.get("rationale", ""),
            color_id=TIER_COLOR.get(task.get("tier", "bronze")),
        )


async def create_recurring_events() -> None:
    today_str = date.today().isoformat()
    weekday = date.today().weekday()  # 0=Mon

    events = []
    if weekday in (0, 2, 4):
        events.append({"summary": "[GOLD] Morning Gym",       "start": "07:00", "dur": 75,  "color": "5"})
    if weekday < 5:
        events.append({"summary": "[SILVER] Job Search Block", "start": "10:00", "dur": 60,  "color": "7"})
        events.append({"summary": "[SILVER] AI Income Work",   "start": "14:00", "dur": 90,  "color": "7"})
    events.append(    {"summary": "[BRONZE] Evening Review",   "start": "21:00", "dur": 20,  "color": "8"})

    for ev in events:
        await create_event(ev["summary"], today_str, ev["start"], ev["dur"], color_id=ev["color"])


async def reschedule_event(event_id: str, new_start_time: str) -> bool:
    tz = ZoneInfo(config.TIMEZONE)
    today_str = date.today().isoformat()

    try:
        service = _build_service()
        event = service.events().get(
            calendarId=config.GOOGLE_CALENDAR_ID, eventId=event_id
        ).execute()

        old_start = datetime.fromisoformat(event["start"]["dateTime"])
        old_end   = datetime.fromisoformat(event["end"]["dateTime"])
        duration  = old_end - old_start
        new_start = _make_datetime(today_str, new_start_time, tz)
        new_end   = new_start + duration

        event["start"] = {"dateTime": new_start.isoformat(), "timeZone": config.TIMEZONE}
        event["end"]   = {"dateTime": new_end.isoformat(),   "timeZone": config.TIMEZONE}
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
