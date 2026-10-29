from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import structy_bot.sessions as sessions_module
from structy_bot.modules import Module
from structy_bot.sessions import cancel, end, format_duration, status, study
from structy_bot.storage import SessionRecord, append_record, read_records

PDT = timezone(timedelta(hours=-7))
START = datetime(2026, 10, 29, 9, 0, tzinfo=PDT)
MODULES = (
    Module("Hashing", "Hashing", 8, 8),
    Module("Binary Tree I", None, None, 0),
    Module("Binary Tree II", None, None, 0),
    Module("Linked List II", None, None, 0),
)
USER = 123
CAP_HOURS = 6.0


def session_file(data_dir: Path) -> Path:
    return data_dir / "current_session.json"


def history_file(data_dir: Path) -> Path:
    return data_dir / "sessions.jsonl"


def start_hashing(data_dir: Path, at: datetime = START) -> None:
    study(data_dir, USER, "hashing", MODULES, at)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0m"), (59, "0m"), (60, "1m"), (2700, "45m"), (3899, "1h 4m"), (3900, "1h 5m"),
     (3600, "1h 0m"), (51600, "14h 20m"), (-5, "0m")],
)
def test_format_duration(seconds: int, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_study_when_idle_then_status_from_disk_shows_same_session(tmp_path: Path) -> None:
    reply = study(tmp_path, USER, "hashing", MODULES, START)
    assert "Hashing" in reply
    later = START + timedelta(minutes=25)
    shown = status(tmp_path, later)  # fresh call, only the disk carries state
    assert "Hashing" in shown
    assert "25m" in shown
    assert "09:00" in shown


def test_study_stores_canonical_topic(tmp_path: Path) -> None:
    reply = study(tmp_path, USER, "linked-list-ii", MODULES, START)
    assert "Linked List II" in reply
    assert "Linked List II" in session_file(tmp_path).read_text(encoding="utf-8")
    assert "linked-list-ii" not in reply


def test_study_while_running_refuses_and_leaves_session_identical(tmp_path: Path) -> None:
    start_hashing(tmp_path)
    before = session_file(tmp_path).read_bytes()
    later = START + timedelta(minutes=90)
    for topic in ("binary tree i", "zzz-not-a-topic", ""):  # invalid second topic too
        reply = study(tmp_path, USER, topic, MODULES, later)
        assert "Hashing" in reply
        assert "1h 30m" in reply
        assert session_file(tmp_path).read_bytes() == before


@pytest.mark.parametrize("topic", ["binary", "heap", "", "  \t\n "])
def test_unstartable_topics_leave_no_session(tmp_path: Path, topic: str) -> None:
    reply = study(tmp_path, USER, topic, MODULES, START)
    assert not session_file(tmp_path).exists()
    assert "Hashing" in reply or "Binary Tree I" in reply


def test_ambiguous_topic_lists_only_candidates(tmp_path: Path) -> None:
    reply = study(tmp_path, USER, "binary", MODULES, START)
    assert "Binary Tree I" in reply
    assert "Binary Tree II" in reply
    assert "Hashing" not in reply


def test_unknown_topic_lists_all_modules_without_echoing_input(tmp_path: Path) -> None:
    reply = study(tmp_path, USER, "xyzzy-plugh-4242", MODULES, START)
    assert all(m.name in reply for m in MODULES)
    assert "xyzzy" not in reply
    assert "plugh" not in reply


def test_fallback_mode_accepts_free_text_and_says_so(tmp_path: Path) -> None:
    reply = study(tmp_path, USER, "  my   own\ttopic ", None, START)
    assert "fallback" in reply.lower()
    assert "my own topic" in session_file(tmp_path).read_text(encoding="utf-8")


def test_fallback_mode_truncates_to_40_chars(tmp_path: Path) -> None:
    study(tmp_path, USER, "a" * 100, None, START)
    assert "a" * 40 in session_file(tmp_path).read_text(encoding="utf-8")
    assert "a" * 41 not in session_file(tmp_path).read_text(encoding="utf-8")


def test_fallback_mode_refuses_empty_topic(tmp_path: Path) -> None:
    study(tmp_path, USER, " \x00 ", None, START)
    assert not session_file(tmp_path).exists()


def test_corrupt_session_file_is_reported_moved_aside_and_ignored(tmp_path: Path) -> None:
    session_file(tmp_path).write_text("{not json", encoding="utf-8")
    reply = study(tmp_path, USER, "hashing", MODULES, START)
    assert "aside" in reply
    assert (tmp_path / "current_session.corrupt.json").exists()
    assert "Hashing" in session_file(tmp_path).read_text(encoding="utf-8")


def test_status_corrupt_file_reported_then_idle(tmp_path: Path) -> None:
    session_file(tmp_path).write_text("{not json", encoding="utf-8")
    reply = status(tmp_path, START)
    assert "aside" in reply
    assert "no session" in reply.lower()
    assert not session_file(tmp_path).exists()


def test_status_idle(tmp_path: Path) -> None:
    assert "no session" in status(tmp_path, START).lower()


def test_status_elapsed_is_not_capped(tmp_path: Path) -> None:
    start_hashing(tmp_path)
    assert "14h 20m" in status(tmp_path, START + timedelta(hours=14, minutes=20))


def test_status_negative_elapsed_shows_zero(tmp_path: Path) -> None:
    start_hashing(tmp_path)
    assert "0m" in status(tmp_path, START - timedelta(minutes=10))


def test_end_without_session_logs_nothing(tmp_path: Path) -> None:
    outcome = end(tmp_path, START, CAP_HOURS)
    assert outcome.record is None
    assert "no session" in outcome.reply.lower()
    assert not history_file(tmp_path).exists()


def test_end_59_seconds_is_discarded(tmp_path: Path) -> None:
    start_hashing(tmp_path)
    outcome = end(tmp_path, START + timedelta(seconds=59), CAP_HOURS)
    assert outcome.record is None
    assert "under 1 minute" in outcome.reply
    assert not session_file(tmp_path).exists()
    assert not history_file(tmp_path).exists()


def test_end_60_seconds_is_logged(tmp_path: Path) -> None:
    start_hashing(tmp_path)
    now = START + timedelta(seconds=60)
    outcome = end(tmp_path, now, CAP_HOURS)
    assert outcome.record is not None
    assert (outcome.record.real_seconds, outcome.record.logged_seconds) == (60, 60)
    assert outcome.record.topic == "Hashing"
    assert outcome.record.user_id == USER
    assert outcome.record.end == now
    assert not outcome.record.capped
    assert not session_file(tmp_path).exists()
    assert read_records(tmp_path)[0] == [outcome.record]
    assert "Hashing" in outcome.reply
    assert "1m" in outcome.reply


def test_end_normal_session_reply_states_duration_and_is_not_capped(tmp_path: Path) -> None:
    start_hashing(tmp_path)
    outcome = end(tmp_path, START + timedelta(minutes=45), CAP_HOURS)
    assert outcome.record is not None
    assert outcome.record.logged_seconds == 2700
    assert "45m" in outcome.reply


def test_end_over_cap_logs_cap_and_reply_has_real_and_logged(tmp_path: Path) -> None:
    start = datetime(2026, 10, 28, 22, 0, tzinfo=PDT)
    start_hashing(tmp_path, start)
    outcome = end(tmp_path, start + timedelta(hours=14, minutes=20), CAP_HOURS)
    record = outcome.record
    assert record is not None
    assert (record.real_seconds, record.logged_seconds, record.capped) == (51600, 21600, True)
    assert "14h 20m" in outcome.reply
    assert "6h 0m" in outcome.reply
    assert read_records(tmp_path)[0] == [record]


def test_end_exactly_at_cap_is_not_capped(tmp_path: Path) -> None:
    start_hashing(tmp_path)
    outcome = end(tmp_path, START + timedelta(hours=6), CAP_HOURS)
    assert outcome.record is not None
    assert (outcome.record.logged_seconds, outcome.record.capped) == (21600, False)


def test_cancel_removes_session_and_logs_nothing(tmp_path: Path) -> None:
    start_hashing(tmp_path)
    reply = cancel(tmp_path)
    assert "Hashing" in reply
    assert not session_file(tmp_path).exists()
    assert not history_file(tmp_path).exists()


def test_cancel_idle(tmp_path: Path) -> None:
    assert "no session" in cancel(tmp_path).lower()


def test_end_with_backwards_clock_discards_and_says_so(tmp_path: Path) -> None:
    start_hashing(tmp_path)
    outcome = end(tmp_path, START - timedelta(minutes=5), CAP_HOURS)
    assert outcome.record is None
    assert "backwards" in outcome.reply
    assert not session_file(tmp_path).exists()
    assert not history_file(tmp_path).exists()


def test_record_is_written_before_session_file_is_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start_hashing(tmp_path)
    original_delete = sessions_module.delete_current_session

    def failing_delete(data_dir: Path) -> None:
        raise OSError("disk went away")

    monkeypatch.setattr(sessions_module, "delete_current_session", failing_delete)
    now = START + timedelta(minutes=30)
    with pytest.raises(OSError):
        end(tmp_path, now, CAP_HOURS)
    assert len(read_records(tmp_path)[0]) == 1
    assert session_file(tmp_path).exists()

    monkeypatch.setattr(sessions_module, "delete_current_session", original_delete)
    retry = end(tmp_path, now + timedelta(minutes=1), CAP_HOURS)
    assert retry.record is not None  # still treated as logged, so a sync should follow
    assert len(read_records(tmp_path)[0]) == 1
    assert not session_file(tmp_path).exists()


def test_append_failure_keeps_session_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start_hashing(tmp_path)
    before = session_file(tmp_path).read_bytes()

    def failing_append(*args: object, **kwargs: object) -> bool:
        raise OSError("cannot write history")

    monkeypatch.setattr(sessions_module, "append_record", failing_append)
    with pytest.raises(OSError):
        end(tmp_path, START + timedelta(minutes=30), CAP_HOURS)
    assert session_file(tmp_path).read_bytes() == before


def test_retry_of_already_logged_session_reports_the_stored_record(tmp_path: Path) -> None:
    start_hashing(tmp_path)
    stored = SessionRecord(
        USER, "Hashing", START, START + timedelta(minutes=30), 1800, 1800, False
    )
    assert append_record(tmp_path, stored)

    outcome = end(tmp_path, START + timedelta(hours=8), CAP_HOURS)  # would be capped if rebuilt

    assert outcome.record == stored
    assert "30m" in outcome.reply
    assert "capped" not in outcome.reply
    assert read_records(tmp_path)[0] == [stored]
    assert not session_file(tmp_path).exists()
