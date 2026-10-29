# Structy-Bot

A private, owner-only Discord bot that times Structy study sessions. `!study` starts one, `!end` records it and runs the existing Structy-Hub sync script. SPEC.md is the source of truth.

This is a personal practice project, not a hosted service. It runs on one person's Windows PC (the single-instance lock uses `msvcrt`), serves one owner, and its sync step depends on that owner's own Structy-Hub repo and Anki data.

## Commands

| Command | What it does |
|---|---|
| `!study <topic>` | Start a session. The topic must match a module in `modules.json` (name or unique prefix, ignoring case, spaces and hyphens). |
| `!end` | End the session, record it, then run the sync and post its result. Under 1 minute is discarded. Over `MAX_SESSION_HOURS` is logged at the cap. |
| `!status` | Show the running session and elapsed time. |
| `!cancel` | Discard the running session without logging it or syncing. |
| `!stats` | Last 7 days: session count, total time, time per topic, streak. |
| `!progress` | Per-module solved counts and overall percent. Needs a valid `modules.json`. |
| `!topics` | List the topics `!study` accepts: `modules.json` modules, then topics you added. |
| `!addtopic <name>` | Add your own topic (up to 50), usable with `!study` right away. Stored in `data\custom_topics.json`; `!progress` ignores it. |

Only `OWNER_ID` can use these, and only in `CHANNEL_ID`. Everyone else gets no reply.

## One-time setup

1. **Create the bot.** In the Discord Developer Portal, make a New Application, open Bot, and reset the token (you see it once; never paste it into chat or commit it).
2. **Enable the intent.** Under Bot, Privileged Gateway Intents, turn on **Message Content Intent**.
3. **Invite it.** OAuth2, URL Generator, scope `bot`, permissions View Channels, Send Messages, Read Message History. Open the URL and add the bot to a private server.
4. **Get your IDs.** In Discord, Settings, Advanced, turn on Developer Mode. Right-click yourself and the channel, Copy ID.
5. **Create `.env`.** Copy `.env.example` to `.env` and fill in `DISCORD_TOKEN`, `OWNER_ID`, `CHANNEL_ID`. `.env` is gitignored; never commit it.
6. **Optional: module list.** Free-text topics are accepted only until the first topic exists (`!addtopic`, or a valid `modules.json`); `!progress` needs `modules.json`. To try the real thing before the Structy-Hub project adds one, create `data\modules.json` here and set `MODULES_PATH` to it in `.env`:

```json
{
  "modules": [
    {"name": "Introduction", "folder": "Introduction", "total_coding_problems": 5, "solved_before_repo": 4},
    {"name": "Linked List I", "folder": "Linked-List-I", "total_coding_problems": 11, "solved_before_repo": 8},
    {"name": "Binary Tree I", "folder": "Binary-Tree-I", "total_coding_problems": 14, "solved_before_repo": 9},
    {"name": "Graph I", "folder": null, "total_coding_problems": null, "solved_before_repo": 0}
  ]
}
```

`folder` must be a single folder name under `HUB_PATH`. `solved_before_repo` plays the role of `BASELINE` in `update_readme.py`.

## Run

From this folder in PowerShell:

```
$env:PYTHONPATH = "src"
.venv\Scripts\python -m structy_bot.bot
```

A missing or invalid required setting prints `Configuration error: ...` naming the variable and exits.

## Tests

```
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check .
```

## Smoke checklist (first run against real Discord)

**Read before step 7.** `!end` runs the real `sync_progress.ps1`. It pulls Structy-Hub and may commit and push a README change. Run `git status` in Structy-Hub first. The script skips (and says so) if tracked files have uncommitted changes.

1. Start the bot. Expect no errors, and no reply in the channel.
2. From another Discord account in the same channel, send `!status`. Expect no reply.
3. From your account in a different channel, send `!status`. Expect no reply.
4. `!status` in the right channel. Expect "no session running".
5. `!study xyz`. Expect a refusal listing the valid topics (or fallback mode if there is no `modules.json`).
6. `!study linked-list-i`. Expect confirmation with the canonical topic. Stop the bot (Ctrl+C), start it again, send `!status`. Expect the same session.
7. Wait over a minute, then `!end`. Expect the record reply, then a second message with the sync result (`No change`, `Pushed README update`, or `Skipped: ...`). Check `data\sessions.jsonl` has one line.
8. `!study heap` then `!end` right away. Expect "under 1 minute, not logged" and no sync.
9. `!study binary`. Expect an "ambiguous" or specific reply, never a pinged name.
10. `!stats`. Expect today's session counted and a streak of at least 1.
11. `!progress`. Expect per-module lines matching your README Solutions table.
12. `!end foo` and `!status now`. Expect "takes no arguments".
13. Without `modules.json`, `!study @everyone`. Expect no ping and escaped text.
14. `!study linked-list-i`, then `!cancel`. Expect nothing logged.

## A possible public version

A version other people could use is a possible future project, not something this repo does today. It would be a new design with its own spec, because it would need things v1 deliberately leaves out:

- Always-on hosting instead of a terminal window on one PC.
- Real per-user storage (a database) and a per-user timezone.
- No Structy-Hub sync for other users: that step only works with the owner's own repo and Anki data, so a public version would be the timer, stats and topics only.
- Rate limits, abuse handling, a privacy policy, and Discord's verification once the bot is in many servers.

v1 keeps a few doors open: every record stores a `user_id`, storage sits behind one small module, and the "which day does a session belong to" rule lives in one function.

## Known limits

See SPEC.md section 13. Notable: history stores the topic as text, so renaming a module splits its stats; the sync lock cannot see a manual run of the script.
