import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from structy_bot.storage import (
    CurrentSession,
    SessionRecord,
    append_record,
    delete_current_session,
    read_current_session,
    read_records,
    reconcile_startup,
    write_current_session,
)

PDT = timezone(timedelta(hours=-7))
START = datetime(2026, 10, 29, 9, 0, tzinfo=PDT)
END = datetime(2026, 10, 29, 9, 45, tzinfo=PDT)


def session(**changes: object) -> CurrentSession:
    fields = {"user_id": 123, "topic": "Hashing", "start": START} | changes
    return CurrentSession(**fields)  # type: ignore[arg-type]


def record(**changes: object) -> SessionRecord:
    fields = {
        "user_id": 123,
        "topic": "Hashing",
        "start": START,
        "end": END,
        "real_seconds": 2700,
        "logged_seconds": 2700,
        "capped": False,
    } | changes
    return SessionRecord(**fields)  # type: ignore[arg-type]


def good_line(**changes: object) -> str:
    fields = {
        "user_id": 1,
        "topic": "Hashing",
        "start": "2026-10-29T09:00:00-07:00",
        "end": "2026-10-29T09:45:00-07:00",
        "real_seconds": 2700,
        "logged_seconds": 2700,
        "capped": False,
    } | changes
    return json.dumps(fields)


def session_path(data_dir: Path) -> Path:
    return data_dir / "current_session.json"


def history_path(data_dir: Path) -> Path:
    return data_dir / "sessions.jsonl"


# current_session.json

def test_session_round_trips_with_aware_start(tmp_path: Path) -> None:
    write_current_session(tmp_path, session())
    loaded, corrupt = read_current_session(tmp_path)
    assert loaded == session()
    assert loaded is not None and loaded.start.utcoffset() == timedelta(hours=-7)
    assert corrupt is False


def test_write_creates_missing_data_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "nested" / "data"
    write_current_session(data_dir, session())
    assert read_current_session(data_dir) == (session(), False)


def test_write_leaves_no_temp_files(tmp_path: Path) -> None:
    write_current_session(tmp_path, session())
    assert [p.name for p in tmp_path.iterdir()] == ["current_session.json"]


def test_write_overwrites_existing_session(tmp_path: Path) -> None:
    write_current_session(tmp_path, session())
    write_current_session(tmp_path, session(topic="Graph I"))
    assert read_current_session(tmp_path) == (session(topic="Graph I"), False)
    assert [p.name for p in tmp_path.iterdir()] == ["current_session.json"]


def test_non_ascii_topic_round_trips(tmp_path: Path) -> None:
    write_current_session(tmp_path, session(topic="Ünïcode 日本語"))
    append_record(tmp_path, record(topic="Ünïcode 日本語"))
    assert read_current_session(tmp_path)[0] == session(topic="Ünïcode 日本語")
    assert read_records(tmp_path)[0][0].topic == "Ünïcode 日本語"


def test_absent_session_file(tmp_path: Path) -> None:
    assert read_current_session(tmp_path) == (None, False)
    assert read_current_session(tmp_path / "missing") == (None, False)


BAD_SESSIONS = {
    "not json": b"{not json",
    "empty": b"",
    "not an object": b"[1, 2]",
    "missing field": b'{"user_id": 1, "topic": "A"}',
    "bool user_id": b'{"user_id": true, "topic": "A", "start": "2026-10-29T09:00:00-07:00"}',
    "str user_id": b'{"user_id": "1", "topic": "A", "start": "2026-10-29T09:00:00-07:00"}',
    "non-str topic": b'{"user_id": 1, "topic": 5, "start": "2026-10-29T09:00:00-07:00"}',
    "non-str start": b'{"user_id": 1, "topic": "A", "start": 5}',
    "naive start": b'{"user_id": 1, "topic": "A", "start": "2026-10-29T09:00:00"}',
    "bad start": b'{"user_id": 1, "topic": "A", "start": "yesterday"}',
    "invalid utf8": b"\xff\xfe\x00",
}


@pytest.mark.parametrize("content", BAD_SESSIONS.values(), ids=BAD_SESSIONS.keys())
def test_corrupt_session_is_renamed_aside_with_bytes_preserved(
    tmp_path: Path, content: bytes
) -> None:
    session_path(tmp_path).write_bytes(content)
    assert read_current_session(tmp_path) == (None, True)
    assert not session_path(tmp_path).exists()
    assert (tmp_path / "current_session.corrupt.json").read_bytes() == content
    assert read_current_session(tmp_path) == (None, False)


def test_second_corruption_does_not_overwrite_first_aside_file(tmp_path: Path) -> None:
    session_path(tmp_path).write_bytes(b"first")
    read_current_session(tmp_path)
    session_path(tmp_path).write_bytes(b"second")
    read_current_session(tmp_path)
    session_path(tmp_path).write_bytes(b"third")
    assert read_current_session(tmp_path) == (None, True)
    assert (tmp_path / "current_session.corrupt.json").read_bytes() == b"first"
    assert (tmp_path / "current_session.corrupt-1.json").read_bytes() == b"second"
    assert (tmp_path / "current_session.corrupt-2.json").read_bytes() == b"third"


def test_delete_session(tmp_path: Path) -> None:
    write_current_session(tmp_path, session())
    delete_current_session(tmp_path)
    assert not session_path(tmp_path).exists()


def test_delete_missing_session_is_fine(tmp_path: Path) -> None:
    delete_current_session(tmp_path)
    delete_current_session(tmp_path / "missing")


# sessions.jsonl

def test_append_writes_one_line_and_returns_true(tmp_path: Path) -> None:
    assert append_record(tmp_path / "data", record()) is True
    text = history_path(tmp_path / "data").read_text(encoding="utf-8")
    assert text.endswith("\n") and text.count("\n") == 1
    saved = json.loads(text)
    assert saved == {
        "user_id": 123,
        "topic": "Hashing",
        "start": "2026-10-29T09:00:00-07:00",
        "end": "2026-10-29T09:45:00-07:00",
        "real_seconds": 2700,
        "logged_seconds": 2700,
        "capped": False,
    }
    assert read_records(tmp_path / "data") == ([record()], 0)


def test_appending_same_session_twice_leaves_one_record(tmp_path: Path) -> None:
    assert append_record(tmp_path, record()) is True
    assert append_record(tmp_path, record()) is False
    assert read_records(tmp_path) == ([record()], 0)


def test_same_instant_with_different_offset_is_a_duplicate(tmp_path: Path) -> None:
    append_record(tmp_path, record())
    same_instant = record(start=START.astimezone(UTC), end=END.astimezone(UTC))
    assert append_record(tmp_path, same_instant) is False
    assert len(read_records(tmp_path)[0]) == 1


def test_same_start_different_user_is_distinct(tmp_path: Path) -> None:
    assert append_record(tmp_path, record()) is True
    assert append_record(tmp_path, record(user_id=456)) is True
    assert len(read_records(tmp_path)[0]) == 2


def test_different_start_same_user_is_distinct(tmp_path: Path) -> None:
    append_record(tmp_path, record())
    assert append_record(tmp_path, record(start=START + timedelta(hours=1))) is True


def test_append_after_truncated_final_line(tmp_path: Path) -> None:
    append_record(tmp_path, record(start=START - timedelta(days=2)))
    append_record(tmp_path, record(start=START - timedelta(days=1)))
    with history_path(tmp_path).open("ab") as handle:
        handle.write(b'{"user_id": 123, "topic": "Hash')
    assert append_record(tmp_path, record()) is True
    records, skipped = read_records(tmp_path)
    assert [r.start for r in records] == [
        START - timedelta(days=2),
        START - timedelta(days=1),
        START,
    ]
    assert skipped == 1


def test_append_does_not_add_blank_line_when_file_ends_with_newline(tmp_path: Path) -> None:
    append_record(tmp_path, record(start=START - timedelta(days=1)))
    append_record(tmp_path, record())
    assert b"\n\n" not in history_path(tmp_path).read_bytes()


def test_read_skips_bad_lines_and_counts_them(tmp_path: Path) -> None:
    lines = [
        good_line(user_id=1),
        "this is garbage",
        "",
        "[1, 2, 3]",
        '"just a string"',
        good_line(user_id=2, start="2026-10-29T10:00:00-07:00"),
        "   ",
        json.dumps({"user_id": 3, "topic": "A"}),
        good_line(start="2026-10-29T09:00:00"),
        good_line(end="2026-10-29T09:45:00"),
        good_line(logged_seconds=-1),
        good_line(real_seconds=-5),
        good_line(user_id=True),
        good_line(real_seconds=1.5),
        good_line(real_seconds="2700"),
        good_line(capped="no"),
        good_line(topic=None),
        good_line(start="not a date"),
        '{"user_id": 1, "topic": "Hash',
        good_line(user_id=4, start="2026-10-29T11:00:00-07:00", capped=True),
    ]
    history_path(tmp_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    records, skipped = read_records(tmp_path)
    assert [r.user_id for r in records] == [1, 2, 4]
    assert records[2].capped is True
    assert skipped == 15


def test_read_counts_invalid_utf8_line_and_keeps_others(tmp_path: Path) -> None:
    content = good_line(user_id=1).encode() + b"\n\xff\xfe\n" + good_line(user_id=2).encode()
    history_path(tmp_path).write_bytes(content)
    records, skipped = read_records(tmp_path)
    assert [r.user_id for r in records] == [1, 2]
    assert skipped == 1


def test_read_accepts_crlf_line_endings(tmp_path: Path) -> None:
    content = (good_line(user_id=1) + "\r\n" + good_line(user_id=2) + "\r\n").encode()
    history_path(tmp_path).write_bytes(content)
    assert read_records(tmp_path)[1] == 0


def test_read_missing_or_empty_history(tmp_path: Path) -> None:
    assert read_records(tmp_path) == ([], 0)
    assert read_records(tmp_path / "missing") == ([], 0)
    history_path(tmp_path).write_text("", encoding="utf-8")
    assert read_records(tmp_path) == ([], 0)


# startup reconciliation

def test_reconcile_deletes_session_already_logged(tmp_path: Path) -> None:
    write_current_session(tmp_path, session())
    append_record(tmp_path, record())
    before = history_path(tmp_path).read_bytes()
    assert reconcile_startup(tmp_path) is True
    assert not session_path(tmp_path).exists()
    assert history_path(tmp_path).read_bytes() == before


def test_reconcile_matches_same_instant_in_other_offset(tmp_path: Path) -> None:
    write_current_session(tmp_path, session(start=START.astimezone(UTC)))
    append_record(tmp_path, record())
    assert reconcile_startup(tmp_path) is True


def test_reconcile_leaves_session_when_no_record_matches(tmp_path: Path) -> None:
    write_current_session(tmp_path, session())
    append_record(tmp_path, record(user_id=456))
    append_record(tmp_path, record(start=START - timedelta(days=1)))
    before = history_path(tmp_path).read_bytes()
    assert reconcile_startup(tmp_path) is False
    assert read_current_session(tmp_path) == (session(), False)
    assert history_path(tmp_path).read_bytes() == before


def test_reconcile_with_no_session_or_no_history(tmp_path: Path) -> None:
    assert reconcile_startup(tmp_path) is False
    write_current_session(tmp_path, session())
    assert reconcile_startup(tmp_path) is False
    assert not history_path(tmp_path).exists()


def test_reconcile_with_corrupt_session_renames_it_aside(tmp_path: Path) -> None:
    session_path(tmp_path).write_bytes(b"{broken")
    assert reconcile_startup(tmp_path) is False
    assert (tmp_path / "current_session.corrupt.json").read_bytes() == b"{broken"
