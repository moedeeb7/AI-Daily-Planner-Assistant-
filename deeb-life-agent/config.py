import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        print(f"[ERROR] Missing required environment variable: {key}", file=sys.stderr)
        print(f"        Copy .env.example to .env and fill in {key}", file=sys.stderr)
        sys.exit(1)
    return val


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


# ── Credentials ───────────────────────────────────────────────────────────────
TELEGRAM_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: str = _require("TELEGRAM_CHAT_ID")
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")

GOOGLE_CREDENTIALS_FILE: str = os.getenv(
    "GOOGLE_CREDENTIALS_FILE", str(BASE_DIR / "google_credentials.json")
)
GOOGLE_TOKEN_FILE: str = os.getenv(
    "GOOGLE_TOKEN_FILE", str(BASE_DIR / "google_token.json")
)
GOOGLE_CALENDAR_ID: str = os.getenv("GOOGLE_CALENDAR_ID", "primary")

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH: str = str(BASE_DIR / "data" / "agent.db")

# ── AI Model ──────────────────────────────────────────────────────────────────
CLAUDE_MODEL: str = "claude-sonnet-4-6"
MAX_TOKENS: int = 2048

# ── Timezone ──────────────────────────────────────────────────────────────────
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Riyadh")

# ── Schedule times (24-hour) ──────────────────────────────────────────────────
MORNING_CHECKIN_HOUR: int = _int("MORNING_CHECKIN_HOUR", 7)
MORNING_CHECKIN_MINUTE: int = _int("MORNING_CHECKIN_MINUTE", 0)
EVENING_REVIEW_HOUR: int = _int("EVENING_REVIEW_HOUR", 21)
EVENING_REVIEW_MINUTE: int = _int("EVENING_REVIEW_MINUTE", 0)
WEEKLY_REPORT_DAY: str = os.getenv("WEEKLY_REPORT_DAY", "sun")
WEEKLY_REPORT_HOUR: int = _int("WEEKLY_REPORT_HOUR", 8)

# ── Follow-up ─────────────────────────────────────────────────────────────────
FOLLOWUP_MINUTES: int = _int("FOLLOWUP_MINUTES", 12)
MAX_FOLLOWUPS: int = _int("MAX_FOLLOWUPS", 2)

# ── Diet ──────────────────────────────────────────────────────────────────────
MIN_PROTEIN_G: int = _int("MIN_PROTEIN_G", 100)
TARGET_CALORIES: int = _int("TARGET_CALORIES", 3000)

# ── Paths ─────────────────────────────────────────────────────────────────────
MEMORY_DIR: Path = BASE_DIR / "memory"
PROMPTS_DIR: Path = BASE_DIR / "prompts"

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# ── Task tier config ──────────────────────────────────────────────────────────
DAILY_GOLD_REQUIRED: int = 1
DAILY_SILVER_REQUIRED: int = 2
DAILY_BRONZE_REQUIRED: int = 3
