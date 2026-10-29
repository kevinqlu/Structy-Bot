import json
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from pathlib import Path

from structy_bot.stats import Stats, compute_stats, format_stats, session_day, stats
from structy_bot.storage import SessionRecord, append_record

PDT = timezone(timedelta(hours=-7))
USER = 123
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=PDT)


def rec(
    topic: str, month: int, day: int, hour: int, minute: int = 0, *, seconds: int = 1800,
    tz: timezone = PDT,
) -> SessionRecord:
    start = datetime(2026, month, day, hour, minute, tzinfo=tz)
    return SessionRecord(
        USER, topic, start, start + timedelta(seconds=seconds), seconds, seconds, False
    )


def section_14_history() -> list[SessionRecord]:
    return [
        rec("Hashing", 10, 29, 9, seconds=30 * 60),
        rec("Hashing", 10, 28, 20, seconds=45 * 60),
        rec("Big O Notation", 10, 26, 18, seconds=20 * 60),
        rec("Introduction", 10, 23, 0, 10, seconds=15 * 60),
        rec("Introduction", 10, 22, 23, 50, seconds=40 * 60),
    ]


def test_session_day_converts_stored_offset_to_local_tz() -> None:
    start = datetime(2026, 10, 28, 23, 30, tzinfo=PDT)
    assert session_day(start, UTC) == date(2026, 10, 29)
    assert session_day(start, PDT) == date(2026, 10, 28)


def test_session_day_without_tz_uses_system_timezone() -> None:
    start = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    assert session_day(start) == start.astimezone().date()


def test_section_14_example() -> None:
    result = compute_stats(section_14_history(), NOW, PDT)
    assert result == Stats(
        session_count=4,
        total_seconds=110 * 60,
        per_topic=(("Hashing", 75 * 60), ("Big O Notation", 20 * 60), ("Introduction", 15 * 60)),
        streak_days=2,
    )
    text = format_stats(result, 0)
    assert "4 sessions" in text
    assert "1h 50m" in text
    assert "Hashing: 1h 15m" in text
    assert "Big O Notation: 20m" in text
    assert "Introduction: 15m" in text
    assert "streak: 2" in text.lower()


def test_window_boundary_pair() -> None:
    first_day = compute_stats([rec("Introduction", 10, 23, 0, 10)], NOW, PDT)
    day_before = compute_stats([rec("Introduction", 10, 22, 23, 50)], NOW, PDT)
    assert first_day.session_count == 1
    assert day_before.session_count == 0


def test_midnight_crossing_counts_once_on_start_day_with_full_duration() -> None:
    crossing = rec("Hashing", 10, 27, 23, 30, seconds=3600)  # ends 10-28 00:30
    now = datetime(2026, 10, 28, 20, 0, tzinfo=PDT)
    result = compute_stats([crossing, rec("Hashing", 10, 28, 14)], now, PDT)
    assert result.session_count == 2
    assert result.streak_days == 2
    alone = compute_stats([crossing], now, PDT)
    assert alone.session_count == 1
    assert alone.total_seconds == 3600
    assert alone.streak_days == 1  # yesterday (10-27) counts; nothing on 10-28


def test_streak_counts_from_yesterday_when_today_has_none() -> None:
    history = [rec("Hashing", 10, 28, 9), rec("Hashing", 10, 27, 9), rec("Hashing", 10, 26, 9)]
    assert compute_stats(history, NOW, PDT).streak_days == 3


def test_streak_is_zero_when_last_session_was_two_days_ago() -> None:
    assert compute_stats([rec("Hashing", 10, 27, 9)], NOW, PDT).streak_days == 0


def test_streak_covers_all_history_not_just_the_window() -> None:
    history = [rec("Hashing", 10, day, 9) for day in range(20, 30)]  # 10-20 .. 10-29
    result = compute_stats(history, NOW, PDT)
    assert result.streak_days == 10
    assert result.session_count == 7
    assert "streak: 10" in format_stats(result, 0).lower()


def test_several_sessions_on_one_day_count_once_for_streak() -> None:
    history = [rec("Hashing", 10, 29, 8), rec("Hashing", 10, 29, 10), rec("Hashing", 10, 29, 11)]
    result = compute_stats(history, NOW, PDT)
    assert result.session_count == 3
    assert result.streak_days == 1


def test_day_comes_from_local_tz_not_the_stored_offset() -> None:
    late = rec("Hashing", 10, 28, 23, 30)  # 10-28 23:30 -07:00 is 10-29 06:30 UTC
    now = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    in_utc = compute_stats([late], now, UTC)
    assert in_utc.streak_days == 1  # today (10-29) has a session when viewed in UTC
    in_pdt = compute_stats([late], datetime(2026, 10, 29, 12, 0, tzinfo=PDT), PDT)
    assert in_pdt.streak_days == 1  # counted from yesterday


def test_totals_sum_seconds_before_rounding() -> None:
    history = [rec("Hashing", 10, 29, 8, seconds=90), rec("Hashing", 10, 29, 9, seconds=90)]
    result = compute_stats(history, NOW, PDT)
    assert result.total_seconds == 180
    text = format_stats(result, 0)
    assert "Hashing: 3m" in text
    assert "2m" not in text


def test_per_topic_sorted_by_seconds_then_name() -> None:
    history = [
        rec("Zeta", 10, 29, 1, seconds=600),
        rec("Alpha", 10, 29, 2, seconds=600),
        rec("Mid", 10, 29, 3, seconds=1200),
        rec("Low", 10, 29, 4, seconds=60),
    ]
    topics = [name for name, _ in compute_stats(history, NOW, PDT).per_topic]
    assert topics == ["Mid", "Alpha", "Zeta", "Low"]


def test_future_dated_sessions_are_ignored() -> None:
    history = [rec("Hashing", 10, 30, 9), rec("Hashing", 10, 31, 9), rec("Hashing", 10, 28, 9)]
    result = compute_stats(history, NOW, PDT)
    assert result.session_count == 1
    assert result.streak_days == 1  # 10-28 only; 10-30 and 10-31 do not extend it


def test_empty_history_message_and_streak() -> None:
    result = compute_stats([], NOW, PDT)
    assert result == Stats(0, 0, (), 0)
    text = format_stats(result, 0)
    assert "no sessions in the last 7 days" in text.lower()
    assert "streak: 0" in text.lower()


def test_empty_window_with_only_old_history_says_so() -> None:
    history = [rec("Hashing", 10, 1, 9)]
    text = format_stats(compute_stats(history, NOW, PDT), 0)
    assert "no sessions in the last 7 days" in text.lower()
    assert "streak: 0" in text.lower()


def test_skipped_note_only_when_lines_were_skipped() -> None:
    result = compute_stats([rec("Hashing", 10, 29, 9)], NOW, PDT)
    assert "skipped" not in format_stats(result, 0).lower()
    assert "2" in format_stats(result, 2)
    assert "skipped" in format_stats(result, 2).lower()


def test_stats_missing_file(tmp_path: Path) -> None:
    text = stats(tmp_path, NOW, PDT)
    assert "no sessions in the last 7 days" in text.lower()
    assert "streak: 0" in text.lower()


def test_stats_reports_corrupt_lines_and_still_counts_good_ones(tmp_path: Path) -> None:
    append_record(tmp_path, rec("Hashing", 10, 29, 9, seconds=1800))
    with (tmp_path / "sessions.jsonl").open("ab") as handle:
        handle.write(b"this is not json\n{\"user_id\": 1}\n")
    append_record(tmp_path, rec("Hashing", 10, 28, 9, seconds=1800))
    text = stats(tmp_path, NOW, PDT)
    assert "2 sessions" in text
    assert "1h 0m" in text
    assert "skipped 2" in text.lower()
    assert "streak: 2" in text.lower()


def _history_line(start: str) -> bytes:
    fields = {
        "user_id": 1, "topic": "X", "start": start, "end": start,
        "real_seconds": 5, "logged_seconds": 5, "capped": False,
    }
    return (json.dumps(fields) + "\n").encode()


def test_stats_survives_absurd_timestamps_among_good_lines(tmp_path: Path) -> None:
    append_record(tmp_path, rec("Hashing", 10, 29, 9, seconds=1800))
    with (tmp_path / "sessions.jsonl").open("ab") as handle:
        handle.write(_history_line("0001-01-01T00:00:00+14:00"))
        handle.write(_history_line("9999-12-31T23:59:59-14:00"))
    text = stats(tmp_path, NOW, PDT)
    assert "1 session," in text
    assert "30m" in text
    assert "skipped 2" in text.lower()


def test_stats_survives_deeply_nested_line(tmp_path: Path) -> None:
    append_record(tmp_path, rec("Hashing", 10, 29, 9, seconds=1800))
    with (tmp_path / "sessions.jsonl").open("ab") as handle:
        handle.write(b"[" * 200_000 + b"\n")
    text = stats(tmp_path, NOW, PDT)
    assert "1 session," in text
    assert "skipped 1" in text.lower()


class _FailsIn2000(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def fromutc(self, dt: datetime) -> datetime:
        if dt.year == 2000:
            raise OverflowError("date value out of range")
        return dt


def test_compute_stats_skips_a_record_whose_day_conversion_fails() -> None:
    odd = SessionRecord(
        USER, "Odd", datetime(2000, 1, 1, tzinfo=UTC), datetime(2000, 1, 1, 1, tzinfo=UTC),
        3600, 3600, False,
    )
    now = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    good = rec("Hashing", 10, 29, 9, seconds=1800, tz=UTC)
    result = compute_stats([odd, good], now, _FailsIn2000())
    assert result.session_count == 1
    assert result.total_seconds == 1800
