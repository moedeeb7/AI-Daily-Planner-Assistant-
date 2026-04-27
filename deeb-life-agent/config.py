import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# ── Credentials ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID: str = os.environ["TELEGRAM_CHAT_ID"]

ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]

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
MORNING_CHECKIN_HOUR: int = int(os.getenv("MORNING_CHECKIN_HOUR", "7"))
MORNING_CHECKIN_MINUTE: int = int(os.getenv("MORNING_CHECKIN_MINUTE", "0"))

EVENING_REVIEW_HOUR: int = int(os.getenv("EVENING_REVIEW_HOUR", "21"))
EVENING_REVIEW_MINUTE: int = int(os.getenv("EVENING_REVIEW_MINUTE", "0"))

WEEKLY_REPORT_DAY: str = os.getenv("WEEKLY_REPORT_DAY", "sun")  # APScheduler day_of_week
WEEKLY_REPORT_HOUR: int = int(os.getenv("WEEKLY_REPORT_HOUR", "8"))

# ── Follow-up ─────────────────────────────────────────────────────────────────
FOLLOWUP_MINUTES: int = int(os.getenv("FOLLOWUP_MINUTES", "12"))
MAX_FOLLOWUPS: int = int(os.getenv("MAX_FOLLOWUPS", "2"))

# ── Diet ──────────────────────────────────────────────────────────────────────
MIN_PROTEIN_G: int = int(os.getenv("MIN_PROTEIN_G", "100"))
TARGET_CALORIES: int = int(os.getenv("TARGET_CALORIES", "3000"))

# ── Paths ─────────────────────────────────────────────────────────────────────
MEMORY_DIR: Path = BASE_DIR / "memory"
PROMPTS_DIR: Path = BASE_DIR / "prompts"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]

# ── Task tier config ──────────────────────────────────────────────────────────
DAILY_GOLD_REQUIRED: int = 1
DAILY_SILVER_REQUIRED: int = 2
DAILY_BRONZE_REQUIRED: int = 3
