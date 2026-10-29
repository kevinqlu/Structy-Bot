from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from structy_bot.modules import Module
from structy_bot.storage import (
    CurrentSession,
    SessionRecord,
    append_record,
    delete_current_session,
    read_current_session,
    read_records,
    write_current_session,
)
from structy_bot.topics import TopicKind, clean_free_text_topic, resolve_topic

MIN_LOGGED_SECONDS = 60
CORRUPT_NOTE = (
    "The saved session file was unreadable; I moved it aside and am treating it as no session.\n"
)
FALLBACK_NOTE = (
    " (The module list is unavailable, so I'm in fallback mode and took your topic as free text.)"
)


@dataclass(frozen=True)
class EndOutcome:
    reply: str
    # Non-None exactly when a record is on disk after this call, so a sync should follow.
    record: SessionRecord | None


def format_duration(seconds: int) -> str:
    hours, minutes = divmod(max(0, seconds) // 60, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def _elapsed(start: datetime, now: datetime) -> int:
    return int((now - start).total_seconds())


def _when(moment: datetime) -> str:
    # Shown in the stored offset on purpose: no timezone conversion.
    return moment.isoformat(timespec="minutes")


def _current(data_dir: Path) -> tuple[CurrentSession | None, str]:
    session, corrupt = read_current_session(data_dir)
    return session, CORRUPT_NOTE if corrupt else ""


def _names(modules: Sequence[Module]) -> str:
    return ", ".join(m.name for m in modules)


def _choose_topic(text: str, modules: Sequence[Module] | None) -> tuple[str | None, str]:
    """Returns (topic, suffix for the confirmation) or (None, refusal reply)."""
    if modules is None:
        topic = clean_free_text_topic(text)
        if topic is None:
            return None, "Please give a topic, for example `!study <topic>`."
        return topic, FALLBACK_NOTE
    match = resolve_topic(text, modules)
    if match.module is not None:
        return match.module.name, ""
    if match.kind is TopicKind.AMBIGUOUS:
        names = _names(match.candidates)
        return None, f"That matches several topics: {names}. Please be more specific (see !topics)."
    if match.kind is TopicKind.EMPTY:
        return None, f"Which topic? Use !topics to see the options: {_names(modules)}."
    return None, f"I don't know that topic. Valid topics: {_names(modules)}. See !topics."


def study(
    data_dir: Path, user_id: int, topic_text: str, modules: Sequence[Module] | None, now: datetime
) -> str:
    session, note = _current(data_dir)
    if session is not None:
        elapsed = format_duration(_elapsed(session.start, now))
        return f"A session is already running: {session.topic}, {elapsed} elapsed."
    topic, message = _choose_topic(topic_text, modules)
    if topic is None:
        return note + message
    write_current_session(data_dir, CurrentSession(user_id, topic, now))
    return f"{note}Started {topic} at {_when(now)}.{message}"


def status(data_dir: Path, now: datetime) -> str:
    session, note = _current(data_dir)
    if session is None:
        return note + "No session is running."
    elapsed = format_duration(_elapsed(session.start, now))  # uncapped; the cap applies only on end
    return f"Running: {session.topic}, started {_when(session.start)}, {elapsed} elapsed."


def cancel(data_dir: Path) -> str:
    session, note = _current(data_dir)
    if session is None:
        return note + "No session is running, nothing to cancel."
    delete_current_session(data_dir)
    return f"Cancelled {session.topic}. Nothing was logged."


def _stored_record(data_dir: Path, wanted: SessionRecord) -> SessionRecord | None:
    for stored in read_records(data_dir)[0]:
        if stored.user_id == wanted.user_id and stored.start == wanted.start:
            return stored
    return None


def _log_session(
    data_dir: Path, session: CurrentSession, now: datetime, real: int, max_session_hours: float
) -> EndOutcome:
    cap = int(max_session_hours * 3600)
    record = SessionRecord(
        session.user_id, session.topic, session.start, now, real, min(real, cap), real > cap
    )
    # Record first, then delete: a crash in between leaves a session that end() can retry.
    if not append_record(data_dir, record):
        # Already logged by an earlier attempt: report what is on disk, not this call's numbers.
        record = _stored_record(data_dir, record) or record
    delete_current_session(data_dir)
    reply = f"Logged {record.topic}: {format_duration(record.logged_seconds)}."
    if record.capped:
        reply += (
            f" The session actually ran {format_duration(record.real_seconds)}, "
            f"so it was capped at {format_duration(record.logged_seconds)}."
        )
    return EndOutcome(reply, record)


def end(data_dir: Path, now: datetime, max_session_hours: float) -> EndOutcome:
    session, note = _current(data_dir)
    if session is None:
        return EndOutcome(note + "No session is running, nothing to log.", None)
    raw = _elapsed(session.start, now)
    real = max(0, raw)
    if real < MIN_LOGGED_SECONDS:
        delete_current_session(data_dir)
        why = "the clock went backwards" if raw < 0 else "under 1 minute"
        return EndOutcome(f"Ended {session.topic}: {why}, not logged.", None)
    return _log_session(data_dir, session, now, real, max_session_hours)
