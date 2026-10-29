from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path

from structy_bot.sessions import format_duration
from structy_bot.storage import SessionRecord, read_records

WINDOW_DAYS = 7


@dataclass(frozen=True)
class Stats:
    session_count: int
    total_seconds: int
    per_topic: tuple[tuple[str, int], ...]  # (topic, seconds), most time first
    streak_days: int


def session_day(start: datetime, local_tz: tzinfo | None = None) -> date:
    """The one place that decides which calendar day a session counts toward (SPEC A1)."""
    # astimezone(None) means the system's current local timezone.
    return start.astimezone(local_tz).date()


def _streak(days: set[date], today: date) -> int:
    # An unfinished today must not reset the streak, so count back from yesterday instead.
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def _dated(
    records: Sequence[SessionRecord], local_tz: tzinfo | None
) -> list[tuple[date, SessionRecord]]:
    dated = []
    for r in records:
        try:
            dated.append((session_day(r.start, local_tz), r))
        except (OverflowError, OSError, ValueError):  # one odd timestamp must not sink !stats
            continue
    return dated


def compute_stats(
    records: Sequence[SessionRecord], now: datetime, local_tz: tzinfo | None = None
) -> Stats:
    today = session_day(now, local_tz)
    window_start = today - timedelta(days=WINDOW_DAYS - 1)
    # Days after today (clock skew) are ignored for the window and the streak alike.
    dated = [(day, r) for day, r in _dated(records, local_tz) if day <= today]
    per_topic: defaultdict[str, int] = defaultdict(int)
    in_window = [r for day, r in dated if day >= window_start]
    for r in in_window:
        per_topic[r.topic] += r.logged_seconds
    ordered = sorted(per_topic.items(), key=lambda item: (-item[1], item[0]))
    return Stats(
        session_count=len(in_window),
        total_seconds=sum(per_topic.values()),
        per_topic=tuple(ordered),
        streak_days=_streak({day for day, _ in dated}, today),
    )


def format_stats(stats: Stats, skipped_lines: int) -> str:
    if stats.session_count == 0:
        lines = ["No sessions in the last 7 days."]
    else:
        noun = "session" if stats.session_count == 1 else "sessions"
        lines = [
            f"Last 7 days: {stats.session_count} {noun}, {format_duration(stats.total_seconds)}",
            *(f"{topic}: {format_duration(secs)}" for topic, secs in stats.per_topic),
        ]
    lines.append(f"Streak: {stats.streak_days} days")
    if skipped_lines > 0:
        lines.append(f"(Skipped {skipped_lines} unreadable history lines.)")
    return "\n".join(lines)


def stats(data_dir: Path, now: datetime, local_tz: tzinfo | None = None) -> str:
    records, skipped = read_records(data_dir)
    return format_stats(compute_stats(records, now, local_tz), skipped)
