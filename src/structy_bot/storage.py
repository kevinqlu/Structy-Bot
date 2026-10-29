import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import count
from pathlib import Path
from typing import Any, BinaryIO

SESSION_FILE = "current_session.json"
HISTORY_FILE = "sessions.jsonl"


@dataclass(frozen=True)
class CurrentSession:
    user_id: int
    topic: str
    start: datetime


@dataclass(frozen=True)
class SessionRecord:
    user_id: int
    topic: str
    start: datetime
    end: datetime
    real_seconds: int
    logged_seconds: int
    capped: bool


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _aware(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def _seconds(value: Any) -> int:
    if not (_is_int(value) and value >= 0):
        raise ValueError("seconds must be a non-negative integer")
    return value


def _common(data: Any) -> tuple[int, str, datetime]:
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    if not _is_int(data["user_id"]) or not isinstance(data["topic"], str):
        raise ValueError("bad user_id or topic")
    return data["user_id"], data["topic"], _aware(data["start"])


def _parse_session(text: str) -> CurrentSession:
    return CurrentSession(*_common(json.loads(text)))


def _parse_record(data: Any) -> SessionRecord:
    user_id, topic, start = _common(data)
    if not isinstance(data["capped"], bool):
        raise ValueError("capped must be a bool")
    return SessionRecord(
        user_id, topic, start, _aware(data["end"]),
        _seconds(data["real_seconds"]), _seconds(data["logged_seconds"]), data["capped"],
    )


def _to_json(item: CurrentSession | SessionRecord) -> str:
    data = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in asdict(item).items()}
    return json.dumps(data)


def _move_aside(path: Path) -> None:
    # Never overwrite an earlier aside file: Kevin may still want to inspect it.
    for n in count():
        suffix = ".corrupt.json" if n == 0 else f".corrupt-{n}.json"
        target = path.with_name(path.stem + suffix)
        if not target.exists():
            try:
                path.rename(target)
                return
            except FileExistsError:
                continue


def write_current_session(data_dir: Path, session: CurrentSession) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=data_dir, prefix="current_session.", suffix=".tmp", delete=False
    )
    try:
        with handle:
            handle.write(_to_json(session))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, data_dir / SESSION_FILE)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def read_current_session(data_dir: Path) -> tuple[CurrentSession | None, bool]:
    path = data_dir / SESSION_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, False
    except UnicodeDecodeError:
        _move_aside(path)
        return None, True
    try:
        return _parse_session(text), False
    except (ValueError, KeyError, TypeError):  # JSONDecodeError is a ValueError
        _move_aside(path)
        return None, True


def delete_current_session(data_dir: Path) -> None:
    (data_dir / SESSION_FILE).unlink(missing_ok=True)


def read_records(data_dir: Path) -> tuple[list[SessionRecord], int]:
    try:
        raw = (data_dir / HISTORY_FILE).read_bytes()
    except FileNotFoundError:
        return [], 0
    records: list[SessionRecord] = []
    skipped = 0
    for line in raw.split(b"\n"):
        if not line.strip():
            continue
        try:
            records.append(_parse_record(json.loads(line.decode("utf-8"))))
        except (ValueError, KeyError, TypeError):  # includes JSON and UTF-8 decode errors
            skipped += 1
    return records, skipped


def _is_logged(data_dir: Path, user_id: int, start: datetime) -> bool:
    # Aware datetimes compare by instant, so a different UTC offset still matches.
    return any(r.user_id == user_id and r.start == start for r in read_records(data_dir)[0])


def _lacks_final_newline(handle: BinaryIO) -> bool:
    # A crash mid-append can leave a final line with no newline; don't glue onto it.
    if handle.seek(0, os.SEEK_END) == 0:
        return False
    handle.seek(-1, os.SEEK_END)
    return handle.read(1) != b"\n"


def append_record(data_dir: Path, record: SessionRecord) -> bool:
    if _is_logged(data_dir, record.user_id, record.start):
        return False
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / HISTORY_FILE).open("ab+") as handle:
        line = (_to_json(record) + "\n").encode("utf-8")
        handle.write((b"\n" if _lacks_final_newline(handle) else b"") + line)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def reconcile_startup(data_dir: Path) -> bool:
    session, _ = read_current_session(data_dir)
    if session is None or not _is_logged(data_dir, session.user_id, session.start):
        return False
    delete_current_session(data_dir)
    return True
