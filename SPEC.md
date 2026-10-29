# Structy-Bot: SPEC (v1 draft 1)

Status: draft for adversarial review. Source of truth for all implementation. If anything here is ambiguous or contradicts itself, stop and ask Kevin.

## 1. Goal

A private, owner-only Discord bot that times Structy study sessions and keeps a durable log. On `!end` it records the session first, then runs the existing Structy-Hub sync script and reports the outcome. Starting and finishing a session is a two-command habit.

The bot runs on Kevin's Windows PC (where the Anki data lives) and only needs to work while the PC is on.

## 2. Non-goals (v1)

- Not multi-user, no web dashboard, no cloud hosting. v1 is private and owner-only. (Future-proofing in section 12 only.)
- No command runs arbitrary input. The bot executes exactly one fixed script with a fixed argument list.
- The bot never writes directly to Structy-Hub (README, Anki data, `modules.json`, any file). It only reads `modules.json` and counts solution files there. The existing sync script, which the bot launches, does all writing.
- No change to `update_readme.py`, `anki_progress.py`, `sync_progress.ps1` or the Roadmap table. Those are a separate project.
- Later, not v1: optional note on `!end`; daily goal and reminders; weekly summary post; auto-start at Windows login; nudge after many sessions in a module without a new solve; `!addtopic`; rolling-24h or timezone-per-user day logic; public hosting.

## 3. Assumptions (decided by default; Kevin may overrule)

- A1. A "day" is the local calendar day of the PC's **current** system timezone (midnight cutoff), applied to the stored instant. A session belongs to the date it **started**. Isolated in one function.
- A2. Maximum logged session length is 6 hours (`MAX_SESSION_HOURS`, configurable). Longer sessions are logged at the cap.
- A3. Sessions under 60 seconds are discarded on `!end`, and the sync does not run for them.
- A4. Sync timeout is 120 seconds (`SYNC_TIMEOUT_SECONDS`, configurable).
- A5. Data lives in a gitignored `data/` folder inside this repo; path from `DATA_DIR`.
- A6. Command names are case-insensitive (`!Study` works).
- A7. If `modules.json` is valid, an unknown topic is refused. Free-text topics are accepted only when the file is missing or malformed.
- A8. Overall progress percent = modules done / total modules in `modules.json`.

## 4. Configuration (`.env`, gitignored; `.env.example` is committed)

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `DISCORD_TOKEN` | yes | | Bot token |
| `OWNER_ID` | yes | | The only Discord user ID allowed |
| `CHANNEL_ID` | yes | | The only channel the bot listens in |
| `SYNC_SCRIPT_PATH` | no | `C:\Users\kevin\code\Structy-Hub\_tools\sync_progress.ps1` | Script the bot runs |
| `SYNC_LOG_PATH` | no | `%LOCALAPPDATA%\structy-sync.log` | Log the script appends to |
| `HUB_PATH` | no | `C:\Users\kevin\code\Structy-Hub` | Structy-Hub root (read-only) |
| `MODULES_PATH` | no | `<HUB_PATH>\modules.json` | Module list (read-only) |
| `DATA_DIR` | no | `<repo>\data` | Where session files live |
| `SYNC_TIMEOUT_SECONDS` | no | 120 | |
| `MAX_SESSION_HOURS` | no | 6 | |

Rules:
- A missing required variable fails at startup with a message naming the variable, nonzero exit, no traceback needed.
- `OWNER_ID` and `CHANNEL_ID` must be integers; otherwise fail at startup naming the variable.
- The token never appears in logs, errors or replies.
- At startup, if `CHANNEL_ID` is not a channel the bot can see, log a warning (the bot still runs).

## 5. Access rules (apply before anything else)

1. Ignore messages from bots, including itself.
2. Ignore any message whose author is not `OWNER_ID`: no reply, no state change, no log of its content.
3. Ignore any message not in `CHANNEL_ID` (DMs included): no reply.
4. Ignore messages that don't start with `!` immediately followed by a known command name (case-insensitive). `! study` (space after `!`) is not a command.
5. All replies use `allowed_mentions=none` (nobody is pinged). Any user-supplied text shown in a reply has mentions escaped.
6. Commands that take no arguments (`!end`, `!status`, `!cancel`, `!stats`, `!progress`) refuse extra text: they reply that the command takes no arguments and do nothing.
7. Commands are handled one at a time, in arrival order. A sync that is still running does not block later commands (for example `!study` right after `!end`).
8. If a command raises an unexpected error, the bot replies with a short generic error (no stack trace, no secrets, no file paths), logs the error server-side without the token, and keeps running. State is never left half-written (storage writes are atomic or append-only).

## 6. Modules file contract (`modules.json`, read-only input)

Shape:

```json
{
  "modules": [
    {"name": "Hashing", "folder": "Hashing", "total_coding_problems": 8, "solved_before_repo": 8},
    {"name": "Linked List I", "folder": "Linked-List-I", "total_coding_problems": 11, "solved_before_repo": 8},
    {"name": "Graph I", "folder": null, "total_coding_problems": null, "solved_before_repo": 0}
  ]
}
```

- `name`: required non-empty string, unique after normalization (section 7).
- `folder`: string or null. Folder name under `HUB_PATH`.
- `total_coding_problems`: positive integer or null (unknown).
- `solved_before_repo`: non-negative integer, default 0 if absent.
- Re-read on every command. Listed order is the display order.
- "Missing or malformed" means: file absent, not valid JSON, no `modules` list, an **empty** `modules` list, any entry violating the rules above, or a `name` that normalizes (section 7) to an empty string (e.g. `"--"`). A malformed file is treated as a whole as unusable (no partial use), and the bot says why in one line (without a stack trace).

## 7. Topic matching

Normalize: lowercase, then remove spaces, hyphens and underscores. Surrounding whitespace of the typed input (including tabs and newlines) is stripped first, so a whitespace-only topic counts as empty.

1. If the normalized input equals one module's normalized name: that module (exact match wins over prefix, so `binary tree i` matches Binary Tree I, not Binary Tree II).
2. Else if it is a prefix of exactly one module's normalized name: that module.
3. Else if it is a prefix of several: reply listing the candidates, ask for a more specific name, start nothing.
4. Else: reply "unknown topic" with the valid topic names, start nothing.

Empty topic (`!study` alone) when the file is valid: refused with the valid topic list. The stored topic is always the module's canonical `name`, never the user's raw text.

Normalization removes only spaces, hyphens and underscores, so a name like `Array and String` matches `arrayandstring` and `array-and-string` and prefixes of those, but not `array string` (the word "and" is part of the name).

Fallback mode (file missing or malformed): any non-empty topic is accepted as free text: whitespace collapsed, control characters removed, capped at 40 characters, mentions escaped when displayed. An empty topic is still refused. The bot tells Kevin it is in fallback mode.

## 8. Commands

Wording below is illustrative. Tests assert the facts (state, numbers, names), not exact strings, except where noted.

### 8.1 `!study <topic>`
- Idle + valid topic: write `current_session.json` (atomically), reply with canonical topic and start time.
- Session already running: refuse; reply shows running topic and elapsed time; state unchanged.
- Invalid or ambiguous topic: see section 7; state unchanged.

### 8.2 `!end` (takes no arguments)
- With any extra text: reply that `!end` takes no arguments; do nothing.
- No session: say so; log nothing; run no sync.
- Order of operations when a session exists:
  1. Compute real elapsed seconds from stored start to now. If that is negative (system clock moved backwards), treat it as 0 and say so in the reply.
  2. If real elapsed < 60 s: delete the session file, reply "under 1 minute, not logged" (or "clock went backwards, not logged"); no record, no sync. Stop.
  3. Logged seconds = min(real, `MAX_SESSION_HOURS` x 3600). If capped, the reply says the real elapsed time and the logged time.
  4. Append one record to `sessions.jsonl` (flushed to disk) **before** any sync. Idempotent: if a record with the same `user_id` and `start` already exists, do not append a duplicate.
  5. Delete `current_session.json`.
  6. Run the sync (section 9) and report the outcome in the channel.
- A sync failure, skip, or timeout never removes or alters the record.

### 8.3 `!status`
- Running: topic, start time, elapsed time (not capped; the cap applies only on `!end`). Idle: says no session running.

### 8.4 `!cancel`
- Running: delete the session file, nothing logged, no sync, reply confirms. Idle: says nothing running.

### 8.5 `!stats`
- Window: today and the previous 6 local calendar days (7 dates). A session is in the window if its **start date** is in it.
- Shows: session count, total logged time, logged time per topic (descending), current streak.
- Streak: number of consecutive local dates with at least one logged session, counting back from today; if today has none, counting back from yesterday (so an unfinished today doesn't reset it). Computed over the whole history, not only the window.
- Empty window: "no sessions in the last 7 days" (streak still shown).
- Unreadable history lines are skipped; the reply notes how many were skipped (section 10).
- Durations display as `Xh Ym`. Totals are computed by summing **seconds** first, then rounding down to whole minutes only for display (so per-topic lines may not visibly add up to the total by up to a minute each; this is intended).
- Stats group by the stored topic string. Renaming a module in `modules.json`, or free-text topics from fallback mode, therefore appear as separate topics (known limitation, section 13).

### 8.6 `!progress`
- Needs a valid `modules.json`; otherwise reply that the config is missing/malformed and show nothing else.
- Per module: solved = count of `.py` files under `HUB_PATH\<folder>` (recursive; skip directories named `__pycache__`, `venv`, `.venv`, `node_modules`, `env`, `build`, `dist`; same rule as `update_readme.py`) + `solved_before_repo`. A null or nonexistent folder counts as 0 files.
- Status (derived, never stored): `done` if `total_coding_problems` is not null and solved >= total; else `in progress` if solved > 0; else `not started`. A module with null total is never `done`.
- Per-module display never shows more than the total (e.g. `11/11`, not `12/11`) even if solved exceeds `total_coding_problems`.
- Summary line: done / in progress / not started counts and overall percent (A8).
- Reply is shown as one message; if over Discord's message limit, split into several.

## 9. Sync integration

- Command (fixed argument list, no shell, nothing from Discord in it):
  `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <SYNC_SCRIPT_PATH>`
  started with `asyncio.create_subprocess_exec`. The event loop is never blocked.
- At most one sync at a time, enforced by a lock. If `!end` arrives while a sync runs, the session is still recorded and the reply says the sync was skipped because one is already running.
- Timeout: `SYNC_TIMEOUT_SECONDS`. On timeout the **whole process tree** is killed (PowerShell and its `git` / `python` children, e.g. via `taskkill /T /F` on the PID), not just `powershell.exe`, so no orphaned `git` is left holding `index.lock`. The reply says the sync timed out and the session was saved.
- Outcome reporting: the exit code alone is not enough (the script exits 0 when it skips). After the process ends, read `SYNC_LOG_PATH`'s last non-empty line. The script logs local time with one-second resolution and no offset (`2026-10-29T10:40:04`). Show the line only if its timestamp is at or after the sync's start time **truncated to the whole second**, compared in local time. Otherwise say no log result was found.
- Outcomes the bot recognizes (displayed verbatim from the log, not interpreted): `No change`, `Pushed README update`, `Skipped: repo has uncommitted changes`, `ERROR: ...`. Exit code nonzero with no fresh log line: report the exit code. Log text is shown with mentions escaped and capped in length.
- Missing script file: reported as an error; the record is still saved.

## 10. Storage

`DATA_DIR` contains:

- `current_session.json`: `{"user_id", "topic", "start"}`. Written atomically (temp file then rename). Its presence means a session is running. Survives restarts.
- `sessions.jsonl`: append-only, one JSON object per line:
  `{"user_id": 123, "topic": "Hashing", "start": "2026-10-29T09:00:00-07:00", "end": "2026-10-29T09:45:00-07:00", "real_seconds": 2700, "logged_seconds": 2700, "capped": false}`
  Timestamps are timezone-aware ISO 8601. `user_id` is stored on every record (future-proofing).
- Startup reconciliation: if `current_session.json` exists and a record in `sessions.jsonl` has the same `user_id` and `start`, the session was already logged (crash between append and delete), so the session file is deleted.
- A corrupt `current_session.json` is reported to Kevin and treated as no session; the file is renamed aside, not silently deleted.
- Reader rule: a line that is not valid JSON or lacks required fields is skipped and counted; it never breaks `!stats`.
- Storage code sits behind one small module so the backend can change later.

## 11. Security requirements (summary of tests)

- Owner-only and channel-only (section 5). Others get no reply and trigger nothing.
- Config from `.env` only; missing value fails at startup naming the variable.
- Message text never reaches a command line or a file path. Topics are mapped to canonical module names; free-text fallback topics are only stored as data.
- No ping can come from the bot's output (`allowed_mentions=none` plus escaping).
- Sync has a timeout, does not block the event loop, and cannot run twice at once.

## 12. Future-proofing (cheap choices only; no public features in v1)

- `user_id` on every record.
- Storage behind one module.
- "Which date does this session count toward" in one function, so calendar-day vs rolling-24h vs per-user timezone can change in one place.

## 13. Known dependencies and duplications

- `solved_before_repo` in `modules.json` duplicates `BASELINE` in `update_readme.py` until that script is changed (separate project) to read `modules.json`.
- The Anki table in the sync script only knows the original six topics; Anki decks and tags for new modules are Kevin's separate work.
- `sync_progress.ps1` hardcodes the Structy-Hub path and the log location; the bot's `HUB_PATH` and `SYNC_LOG_PATH` must agree with it.
- Requires the Message Content intent enabled for the bot in the Discord developer portal.
- The bot's sync lock cannot see other writers: a manual run of the script, or the GitHub Actions workflow pushing at the same moment, can still collide with it. Out of scope for v1.
- History stores the topic as a string. Renaming a module in `modules.json` splits its stats into old and new names. A stable module `id` would fix this and is deferred.
- `!progress` percent is done modules / total modules, rounded to the nearest whole percent with halves rounding up (1 of 8 shows 13%).
- `!progress` counts files with `os.walk(followlinks=False)` and skips the ignored directory names below each module folder. A Windows junction nested inside a module folder may still be followed (untested); only the module folder itself is checked to stay inside `HUB_PATH`.
- If sending the first reply to `!end` fails, the sync still runs and its result is posted.
- This folder is not a git repository yet. `.gitignore` entries for `.env` and `data/` take effect only after Kevin runs `git init`; the bot work never initializes, commits or pushes anything.
- Dependencies: `discord.py`, `python-dotenv` (runtime); `pytest`, `ruff` (dev). Nothing else. No `mypy`.

## 14. Worked examples

Topic matching (valid file with Binary Search, Binary Tree I, Binary Tree II, Linked List I, Linked List II, Graph I, Graph II):

| Input | Result |
|---|---|
| `!study linked-list-ii` | Linked List II |
| `!study Binary Tree I` | Binary Tree I (exact beats prefix of "II") |
| `!study binary` | ambiguous: lists Binary Search, Binary Tree I, Binary Tree II; nothing starts |
| `!study graph` | ambiguous: Graph I, Graph II |
| `!study heap` (not in file) | unknown topic; lists valid topics |
| `!study` | refused; lists valid topics |

`!end` timeline (cap 6 h):

- Start 09:00, `!end` at 09:00:40: discarded, "under 1 minute", no record, no sync.
- Start 09:00, `!end` at 09:45: record real 2700 s, logged 2700 s; sync runs.
- Start 22:00, `!end` at 12:20 next day (14h20m): record real 51600 s, logged 21600 s, capped true; reply states both; sync runs.
- `!end` while sync is running: record saved; reply says sync skipped (already running).

`!stats` (today = 2026-10-29, local; window = 2026-10-23 through 2026-10-29):

| Session start | Topic | Minutes | In window |
|---|---|---|---|
| 10-29 09:00 | Hashing | 30 | yes |
| 10-28 20:00 | Hashing | 45 | yes |
| 10-26 18:00 | Big O Notation | 20 | yes |
| 10-23 00:10 | Introduction | 15 | yes (first day of window) |
| 10-22 23:50 | Introduction | 40 | no |

Expected: 4 sessions, 1h 50m total; Hashing 1h 15m, Big O Notation 20m, Introduction 15m; streak 2 (10-29, 10-28; 10-27 has none).

Midnight crossing: a session 10-27 23:30 to 10-28 00:30 counts once, on 10-27, with its full 60 minutes. With another session on 10-28 14:00, the streak counts 10-27 and 10-28.

`!progress` (illustration; the three modules above plus nothing else): Hashing: 0 files + 8 = 8 >= 8, done. Linked List I: 3 files + 8 = 11 >= 11, done. Graph I: null folder, 0 + 0, not started. Summary: 2 done, 0 in progress, 1 not started, 67%.

## 15. Edge cases (must be handled)

- Bot restarts mid-session: session persists; `!status` shows the same session and elapsed time.
- Bot crashes between appending the record and deleting the session file: next `!end` does not create a duplicate record (idempotency on `user_id` + `start`).
- `modules.json` edited between commands: next command sees the change. Half-written or invalid file: treated as malformed for that command only.
- `modules.json` deleted: `!study <anything>` works as free text; `!progress` reports the config missing.
- `@everyone`, `<@123>`, or `@here` in a topic (fallback mode) or in log text: no ping, text escaped.
- Topic longer than 40 characters (fallback mode): truncated.
- System clock moves backward so elapsed < 0: treated as 0 seconds, so `!end` discards the session and says the clock went backwards. `!status` shows 0.
- Crash after the record is appended but before the session file is deleted: on next start the session file is removed (no phantom running session), and no duplicate record is ever written.
- An unexpected error inside a command: generic reply, bot keeps running, no half-written state.
- `!status foo`, `!cancel foo`, `!stats foo`, `!progress foo`, `!end foo`: refused with "takes no arguments".
- Daylight saving change during a session: elapsed time uses timezone-aware timestamps, so it is true elapsed time.
- History file missing or empty: `!stats` shows no sessions, streak 0.
- Sync script path missing: error reported; record saved.
- Sync log missing or unreadable: reply says no log result found.

## 16. Acceptance tests (plain English)

1. `!study linked-list-i` when idle confirms the start. After a bot restart, `!status` shows the same session.
2. `!study` while a session runs refuses and shows elapsed time; the running session is unchanged.
3. `!end` with no session says so, logs nothing, runs no sync.
4. `!end` writes a record first, then runs the sync and reports its outcome. If the sync fails or times out, the record still exists.
5. A message from any other user, or in any other channel, gets no reply and changes nothing.
6. A topic containing `@everyone` (fallback mode) or log text containing it pings nobody.
7. `!stats` is correct for the section 14 hand-made history, including the 7-day boundary and a streak that crosses midnight.
8. Starting with no token (or no `OWNER_ID`, or no `CHANNEL_ID`) prints an error naming the variable and exits nonzero.
9. A corrupt line in `sessions.jsonl` doesn't break `!stats`, and the skipped count is reported.
10. Adding an entry to `modules.json` makes it a valid topic without a restart.
11. A prefix matching several modules asks for a more specific name and starts nothing.
12. A module with null `total_coding_problems` never shows as done.
13. With `modules.json` deleted, `!study` accepts free text and `!progress` says the config is missing.
14. `!progress` counts equal the README Solutions table "Total" for the same data (file count + `solved_before_repo`).
15. A session under 60 seconds is discarded on `!end`, not logged, and no sync runs.
16. A session over the cap is logged at the cap and the reply states real and logged time.
17. `!cancel` removes the session, logs nothing and runs no sync.
18. `!end` with extra text does nothing and says it takes no arguments.
19. A second `!end` while a sync is in flight records the session and skips the sync with a message; two syncs never overlap.
20. A sync that outlives `SYNC_TIMEOUT_SECONDS` is terminated, and the bot stays responsive throughout.
21. The log line shown is the newest line only when its timestamp is at or after the sync start; an older line is not shown as the result.
22. Appending the same session twice (simulated crash) leaves one record.
23. No code path opens a file under `HUB_PATH` for writing (a test that patches file opening, runs every command, and fails on any write-mode open there).
24. `!Study`, `!END` and `!Status` work (commands are case-insensitive); `! study x` does nothing.
25. In fallback mode a topic over 40 characters is truncated; control characters are removed; an empty topic is refused.
26. A non-integer `OWNER_ID` or `CHANNEL_ID` fails at startup naming the variable.
27. A missing sync script file is reported as an error, and the session record still exists.
28. On timeout the whole process tree is killed (a test with a child process that outlives its parent confirms the child is gone).
29. A sync log line stamped in the same whole second as the sync start is accepted as fresh; one stamped a second earlier is not.
30. Startup with a session file whose `user_id` + `start` already exists in `sessions.jsonl` deletes the session file and writes nothing.
31. `!end` with a backwards clock discards the session and says so.
32. `!status`, `!cancel`, `!stats`, `!progress` and `!end` with extra text refuse and change nothing.
33. An unexpected exception in a command produces a generic reply with no stack trace, and the next command still works.
34. `!progress` never shows solved above total for a module (`11/11`, not `12/11`).
35. `pytest` and `ruff check` both pass with no warnings on the finished slice.
