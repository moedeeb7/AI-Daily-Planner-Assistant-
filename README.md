# Deeb Life Operating System

A production-ready AI agent that functions as daily assistant, life coach, scheduler, fitness coach, job search manager, and AI income strategist — all communicating through Telegram in real time.

---

## What this system does

- Sends a morning check-in at 7 AM and builds a personalized daily plan based on your energy
- Proactively reminds you of tasks, meals, gym, job applications, and AI income work
- Classifies everything you send it (meal logs, workout updates, job applications) and stores it
- Tracks nutrition, weight, workouts, job applications, and AI income progress
- Runs a weekly adaptation engine every Sunday — adjusts your schedule based on real behavior data
- Sends an evening review every night at 9 PM with a structured day recap
- Generates weekly reports with pattern analysis

---

## Project Structure

```
deeb-life-agent/
├── main.py                 # Entry point — starts bot + scheduler
├── config.py               # All configuration from .env
├── telegram_bot.py         # Two-way Telegram interface + command handlers
├── calendar_manager.py     # Google Calendar read/write
├── scheduler.py            # APScheduler — all time-based jobs
├── ai_brain.py             # Claude API — all AI reasoning
├── database.py             # SQLite — all data storage and queries
│
├── memory/
│   ├── user_profile.md     # Deeb's profile, goals, preferences
│   ├── goals.md            # Structured goals with metrics
│   ├── behavior_patterns.md # Updated weekly by adaptation engine
│   ├── coaching_rules.md   # How the agent coaches (non-negotiable rules)
│   ├── energy_rules.md     # Energy-level scheduling logic
│   ├── diet_rules.md       # Nutrition targets and protocols
│   ├── workout_rules.md    # Training structure and rules
│   ├── job_search_rules.md # Job search system and protocols
│   ├── ai_income_rules.md  # AI income 90-day plan
│   └── adaptation_log.md   # Weekly adaptation history
│
├── prompts/
│   ├── morning_checkin.md  # Morning check-in message template
│   ├── daily_planner.md    # Daily plan generation rules
│   ├── pre_task_check.md   # Pre-task reminder template
│   ├── post_task_check.md  # Post-task check-in template
│   ├── journaling_prompt.md # Journal prompt template
│   ├── evening_review.md   # Evening review structure
│   ├── weekly_review.md    # Weekly report structure
│   └── adaptation_prompt.md # Adaptation engine analysis rules
│
├── data/
│   └── agent.db            # SQLite database (auto-created on first run)
│
├── .env.example            # Environment variable template
└── requirements.txt        # Python dependencies
```

---

## Setup

### 1. Clone and install dependencies

```bash
cd deeb-life-agent
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create your Telegram bot

1. Open Telegram and message **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the bot token
4. Message your bot, then get your chat ID by messaging **@userinfobot**

### 3. Get your Anthropic API key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an API key
3. Copy it

### 4. Set up Google Calendar (optional but recommended)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project
3. Enable the **Google Calendar API**
4. Create **OAuth 2.0 credentials** (Desktop app type)
5. Download the credentials JSON file
6. Rename it to `google_credentials.json` and place it in `deeb-life-agent/`
7. On first run, a browser window will open for authentication
8. After auth, `google_token.json` is saved automatically — no re-auth needed

### 5. Configure environment

```bash
cp .env.example .env
# Edit .env with your real values
```

Required variables:
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
ANTHROPIC_API_KEY=...
```

Optional (have defaults):
```
TIMEZONE=Asia/Riyadh
MORNING_CHECKIN_HOUR=7
EVENING_REVIEW_HOUR=21
MIN_PROTEIN_G=100
TARGET_CALORIES=3000
```

### 6. Run

```bash
python main.py
```

The system will:
1. Initialize the SQLite database
2. Start the APScheduler with all scheduled jobs
3. Start the Telegram bot in polling mode
4. Begin sending scheduled messages at configured times

---

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Show available commands |
| `/status` | Quick daily summary — tasks, nutrition, streak |
| `/tasks` | Today's full task list with completion status |
| `/nutrition` | Today's meal log with protein/calorie totals |
| `/weight [kg]` | Log weight or view 14-day history |
| `/jobs` | Job application stats (7d and 30d) |
| `/plan` | Regenerate today's plan |
| `/review` | Trigger evening review now |
| `/adapt` | Run adaptation engine on last 7 days |

---

## How to talk to it

The bot understands free-text messages. Examples:

**Logging meals:**
- "I ate chicken and rice"
- "Had 2 eggs and coffee for breakfast"
- "Just had a protein shake"

**Logging workouts:**
- "Done with gym, 60 minutes bench and rows"
- "Skipped gym today, tired"
- "Went for a 30 minute walk"

**Logging weight:**
- "74.5 kg this morning"
- "Weight today: 73.8"

**Job applications:**
- "Applied to 2 jobs on LinkedIn — Google and Microsoft"
- "Sent applications to 3 companies"

**AI income work:**
- "Watched a tutorial on n8n for 45 minutes"
- "Built a demo automation workflow"
- "Sent 2 cold outreach messages"

**Status updates:**
- "I feel tired today"
- "Energy is low, skipping gym"
- "Slept 5 hours last night"
- "I don't feel like doing anything"

---

## Database Schema

| Table | What it stores |
|-------|---------------|
| `daily_checkins` | Morning energy, mood, appetite, sleep per day |
| `tasks` | All planned tasks with tier, category, completion status |
| `meal_logs` | Every meal with estimated protein and calories |
| `weight_logs` | Weight entries over time |
| `workout_logs` | Gym session completions and notes |
| `job_applications` | Applications with company, role, status, follow-up dates |
| `ai_income_logs` | AI/business tasks by type and completion |
| `conversations` | Full message history (inbound + outbound) |
| `follow_ups` | Scheduled follow-up messages with sent/responded status |
| `behavior_snapshots` | Weekly adaptation engine analysis results |

---

## Scheduled Jobs

| Job | Time | Frequency |
|-----|------|-----------|
| Morning check-in | 07:00 | Daily |
| Breakfast reminder | 08:30 | Daily |
| Gym reminder | 07:15 | Mon/Wed/Fri |
| Job search reminder | 09:30 | Mon–Fri |
| Lunch reminder | 13:00 | Daily |
| AI income reminder | 13:30 | Mon–Fri |
| Afternoon snack | 16:30 | Daily |
| Dinner reminder | 19:00 | Daily |
| Protein check | 20:00 | Daily |
| Journal prompt | 20:30 | Tue/Thu |
| Evening review | 21:00 | Daily |
| Follow-up checker | every 2 min | Always |
| Pre-task checker | every 30 min | Always |
| Adaptation engine | 06:00 | Sunday |
| Weekly report | 08:00 | Sunday |

---

## Adaptation Engine

Every Sunday at 6 AM, the system automatically:

1. Analyzes last 7 days of data
2. Detects: missed task patterns, energy trends, best performance times, successful habits
3. Updates `memory/behavior_patterns.md` with new patterns
4. Appends to `memory/adaptation_log.md`
5. Adjusts: task difficulty, schedule timing, calorie targets, habit frequency
6. Sends a summary to Telegram

You can also trigger it manually with `/adapt`.

---

## Running as a background service (Linux)

Create `/etc/systemd/system/deeb-life-os.service`:

```ini
[Unit]
Description=Deeb Life OS
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/deeb-life-agent
ExecStart=/path/to/venv/bin/python main.py
Restart=always
RestartSec=10
EnvironmentFile=/path/to/deeb-life-agent/.env

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable deeb-life-os
sudo systemctl start deeb-life-os
sudo systemctl status deeb-life-os
```

---

## Customization

### Change your schedule times
Edit `.env`:
```
MORNING_CHECKIN_HOUR=6     # Wake up earlier
EVENING_REVIEW_HOUR=22     # Later evening review
```

### Change nutrition targets
```
MIN_PROTEIN_G=120          # Higher protein goal
TARGET_CALORIES=3200       # More calories
```

### Adjust follow-up timing
```
FOLLOWUP_MINUTES=15        # Wait 15 min before following up
MAX_FOLLOWUPS=3            # Follow up 3 times before going silent
```

### Update your profile
Edit `memory/user_profile.md` directly to update any personal information.
The AI reads this file on every message — changes take effect immediately.
