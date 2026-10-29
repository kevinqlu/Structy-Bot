import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from structy_bot.modules import Module, normalize_name
from structy_bot.topics import clean_free_text_topic

CUSTOM_FILE = "custom_topics.json"
MAX_CUSTOM_TOPICS = 50


@dataclass(frozen=True)
class CustomTopics:
    names: tuple[str, ...]
    malformed: bool


class AddStatus(Enum):
    ADDED = "added"
    EMPTY = "empty"
    DUPLICATE = "duplicate"
    LIMIT_REACHED = "limit_reached"
    MALFORMED_FILE = "malformed_file"


@dataclass(frozen=True)
class AddResult:
    status: AddStatus
    name: str | None = None  # the cleaned name, when ADDED
    existing: str | None = None  # the clashing topic's stored name, when DUPLICATE


_MALFORMED = CustomTopics((), True)


def read_custom_topics(data_dir: Path) -> CustomTopics:
    try:
        data = json.loads((data_dir / CUSTOM_FILE).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return CustomTopics((), False)
    except (OSError, ValueError):  # ValueError covers bad JSON and bad UTF-8
        return _MALFORMED
    names = data.get("topics") if isinstance(data, dict) else None
    if not isinstance(names, list):
        return _MALFORMED
    keys = {normalize_name(n) for n in names if isinstance(n, str) and n.strip()}
    # Distinct valid keys must account for every entry: catches non-strings, blanks,
    # separators-only names ("" key) and duplicates after normalization.
    if len(keys) != len(names) or "" in keys:
        return _MALFORMED
    return CustomTopics(tuple(names), False)


def _write_atomic(data_dir: Path, names: Sequence[str]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=data_dir, prefix="custom_topics.", suffix=".tmp", delete=False
    )
    try:
        with handle:
            handle.write(json.dumps({"topics": list(names)}, ensure_ascii=False, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, data_dir / CUSTOM_FILE)
    except BaseException:
        # Any failure before os.replace completes: drop the temp file, old file untouched.
        Path(handle.name).unlink(missing_ok=True)
        raise


def _find_existing(key: str, names: Sequence[str]) -> str | None:
    return next((n for n in names if normalize_name(n) == key), None)


def add_custom_topic(data_dir: Path, raw_name: str, modules: Sequence[Module] | None) -> AddResult:
    custom = read_custom_topics(data_dir)
    if custom.malformed:
        return AddResult(AddStatus.MALFORMED_FILE)
    cleaned = clean_free_text_topic(raw_name)
    key = normalize_name(cleaned) if cleaned else ""
    if cleaned is None or not key:
        return AddResult(AddStatus.EMPTY)
    existing = _find_existing(key, [m.name for m in modules or ()] + list(custom.names))
    if existing is not None:
        return AddResult(AddStatus.DUPLICATE, existing=existing)
    if len(custom.names) >= MAX_CUSTOM_TOPICS:
        return AddResult(AddStatus.LIMIT_REACHED)
    _write_atomic(data_dir, [*custom.names, cleaned])
    return AddResult(AddStatus.ADDED, name=cleaned)


def effective_topics(modules: Sequence[Module] | None, custom: Sequence[str]) -> tuple[Module, ...]:
    base = tuple(modules or ())
    taken = {normalize_name(m.name) for m in base}
    extra = tuple(
        Module(name, None, None, 0) for name in custom if normalize_name(name) not in taken
    )
    return base + extra
