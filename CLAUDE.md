# Structy-Bot: working agreement

SPEC.md is the source of truth. If it is ambiguous or contradicts itself, stop and ask Kevin. Do not guess and build.

## Roles
- Kevin owns the problem definition, the design and the final review. The agent implements.

## How to work
1. Restate the slice and list assumptions before writing code.
2. Tests first: write failing tests that encode the spec, show them failing, then implement until they pass.
3. One small slice at a time (~150 lines of source code per slice; test lines are not counted but every report states both numbers). No drive-by refactors. No new dependencies (approved: discord.py, python-dotenv, pytest, ruff; no mypy).
4. Run pytest and ruff yourself and show the real output. Never claim something works without evidence.
5. Stop after each slice for Kevin's review.

## Hard rules
- Never commit, push, `git init`, or touch files outside this repo without asking.
- Structy-Hub is read-only input. Never write to it.
- No secrets in code or logs. Config goes in .env (gitignored).
- Never delete or weaken a test to make it pass. If a test looks wrong, say why.

## Style
- Python 3.11+, type hints, small functions, explicit names.
- Comments only where the why isn't obvious.

## End-of-slice report (required)
- What changed (files, rough line count).
- What you decided on your own (flag every judgment call).
- What you're unsure about.
- How Kevin can verify it (exact commands).
- Real pytest and ruff output.
