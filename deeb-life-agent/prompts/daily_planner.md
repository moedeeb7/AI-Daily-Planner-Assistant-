# Daily Planner Prompt

Generate Deeb's complete daily task list based on his morning check-in data.

## Plan requirements
- Exactly 1 gold task (highest impact — gym, job application block, AI income work, or hitting calorie target)
- Exactly 2 silver tasks (supporting actions — meal prep, resume update, learning session, follow-up emails)
- Exactly 3 bronze tasks (small habits — water intake, vitamins, 5-minute evening journal, walk)

## Energy-based rules
- Energy 7–10: Full day. Deep work blocks. Gym as gold. 90-min job/AI sessions.
- Energy 5–6: Standard. Shorten sessions to 45 min. Still hit the gym.
- Energy 3–4: Light day. Gym becomes 25-min walk. 1 job app counts as gold. Light AI task.
- Energy 1–2: Recovery. Eat 3 meals. Short walk. Bronze tasks only. Rest.

## Schedule rules
- Space tasks with realistic gaps
- Do NOT schedule everything back-to-back with no breaks
- Deep work (job, AI income) should be in the morning when possible
- Gym should be early (before 9 AM ideal, before noon acceptable)
- Evening tasks only: journaling, review, light reading

## Output format
The output is a structured JSON plan (handled in code).
The text content for each task should be:
- Specific: not "exercise" but "Bench press + rows + overhead press | 45 min"
- Actionable: starts with a verb
- Time-bound: has a specific scheduled_time in HH:MM format

## Recovery integration
Always include a recovery_note: what Deeb should do if energy drops mid-day.
