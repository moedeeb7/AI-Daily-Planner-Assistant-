# Adaptation Engine Prompt

Used by the adaptation engine every Sunday at 6 AM (before the weekly report).

## Purpose
Analyze Deeb's last 7 days of behavioral data and produce specific, actionable adjustments
to his schedule, task difficulty, habits, and nutrition targets.

## Analysis framework

### 1. Task completion patterns
- Which task tiers are being completed most/least?
- Which categories (gym, diet, job, AI income) are failing most?
- Are failures concentrated on certain days or times?

### 2. Energy patterns
- What is the average energy across the week?
- Is energy trending up, down, or stable?
- What days/times does energy peak?
- Correlation: does low energy predict task failure?

### 3. Nutrition adherence
- Is Deeb hitting 100g protein most days?
- What is the average calorie intake?
- Are there consistent gaps (e.g., always low at breakfast)?

### 4. Weight trend
- Is weight moving in the right direction?
- Rate of change vs. target rate (+0.3–0.5 kg/week)?

### 5. Behavioral consistency
- What habits are becoming automatic (high completion for 2+ weeks)?
- What tasks keep getting skipped?
- Is there a day-of-week pattern?

## Output rules
The output must be actionable and specific. No vague advice.

**Schedule adjustments**: specific time changes
"Move gym reminder from 7:00 to 6:45 — he's more likely to act on it before 7 AM"

**Task difficulty**: increase / decrease / maintain
"Decrease: he completed only 40% of silver tasks — reduce to 1 silver per day this week"

**Calorie adjustment**: based on weight trend
"Increase daily target to 3200 kcal — no weight change in 2 weeks"

**Habit frequency**: based on completion rate
"Journaling: reduce to 1x/week — 2x/week is getting skipped consistently"

## What NOT to adjust
- Core structure (gold/silver/bronze system)
- Morning check-in time (7 AM is fixed)
- Evening review (9 PM is fixed)
- The no-zero-day rule (always at least 1 bronze)

## Memory update rule
After each analysis:
1. Update behavior_patterns.md with new detected patterns
2. Append to adaptation_log.md with a timestamped entry
3. The changes take effect starting Monday of the next week
