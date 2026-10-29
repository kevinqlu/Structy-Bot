import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from structy_bot import sessions
from structy_bot import stats as stats_module
from structy_bot.config import Config
from structy_bot.modules import Module, ModulesError, load_modules
from structy_bot.progress import compute_progress, format_progress
from structy_bot.storage import SessionRecord
from structy_bot.sync import SyncResult, SyncStatus
from structy_bot.topics_store import (
    AddResult,
    AddStatus,
    add_custom_topic,
    effective_topics,
    read_custom_topics,
)

log = logging.getLogger(__name__)

MODULES_PROBLEM = "modules.json is missing or malformed: "
GENERIC_ERROR = "Something went wrong running that command. Please try again."
_COMMAND = re.compile(
    r"!(study|end|status|cancel|stats|progress|topics|addtopic)(?:\s(.*))?",
    re.IGNORECASE | re.DOTALL,
)
# Own version of discord.utils.escape_mentions: that one needs 17+ digit ids, and
# the spec wants any <@123> neutralised.
_MENTION = re.compile(r"@(?=everyone|here|[!&]?\d)")


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    args: str


@dataclass(frozen=True)
class Handled:
    text: str
    record_to_sync: SessionRecord | None = None


def parse_command(content: str) -> ParsedCommand | None:
    match = _COMMAND.fullmatch(content)
    if match is None:
        return None
    return ParsedCommand(match.group(1).lower(), (match.group(2) or "").strip())


def escape_mentions(text: str) -> str:
    return _MENTION.sub("@\N{ZERO WIDTH SPACE}", text)


def _load_modules_or_none(config: Config) -> tuple[Sequence[Module] | None, str]:
    try:
        return load_modules(config.modules_path), ""
    except ModulesError as error:
        return None, str(error)


def _study(args: str, config: Config, now: datetime) -> str:
    modules, problem = _load_modules_or_none(config)
    topics = effective_topics(modules, read_custom_topics(config.data_dir).names)
    if topics:
        return sessions.study(config.data_dir, config.owner_id, args, topics, now)
    lead = f"{MODULES_PROBLEM}{problem}\n" if problem else ""
    return lead + sessions.study(config.data_dir, config.owner_id, args, None, now)


def _topics(config: Config) -> str:
    modules, problem = _load_modules_or_none(config)
    custom = read_custom_topics(config.data_dir)
    lines = [f"{MODULES_PROBLEM}{problem}"] if problem else []
    if custom.malformed:
        lines.append("custom_topics.json is unreadable, so I'm ignoring it.")
    topics = effective_topics(modules, custom.names)
    if not topics:
        lines.append("No topics yet. Free-text topics are accepted. Use `!addtopic <name>` to add.")
    module_count = len(modules or ())
    for number, topic in enumerate(topics, 1):
        lines.append(f"{number}. {topic.name}" + (" (added)" if number > module_count else ""))
    return "\n".join(lines)


def _describe_add(result: AddResult) -> str:
    replies = {
        AddStatus.ADDED: f"Added topic {result.name}. You can use it with !study right away.",
        AddStatus.EMPTY: "That name is empty once cleaned. Please give a usable name.",
        AddStatus.DUPLICATE: f"That topic already exists as {result.existing}.",
        AddStatus.LIMIT_REACHED: (
            "The limit of 50 custom topics is reached. "
            r"You can edit data\custom_topics.json by hand."
        ),
        AddStatus.MALFORMED_FILE: (
            r"data\custom_topics.json is unreadable, so nothing was changed. "
            "Fix or delete it first."
        ),
    }
    return replies[result.status]


def _addtopic(args: str, config: Config) -> str:
    if not args:
        return "Please give a topic name: `!addtopic <name>`."
    modules, _ = _load_modules_or_none(config)
    return _describe_add(add_custom_topic(config.data_dir, args, modules))


def _progress(config: Config) -> str:
    try:
        modules = load_modules(config.modules_path)
    except ModulesError as error:
        return f"{MODULES_PROBLEM}{error}"
    return format_progress(compute_progress(modules, config.hub_path))


def _dispatch(command: ParsedCommand, config: Config, now: datetime) -> Handled:
    if command.name == "study":
        return Handled(_study(command.args, config, now))
    if command.name == "addtopic":
        return Handled(_addtopic(command.args, config))
    if command.args:
        return Handled(f"!{command.name} takes no arguments.")
    if command.name == "end":
        outcome = sessions.end(config.data_dir, now, config.max_session_hours)
        return Handled(outcome.reply, outcome.record)
    if command.name == "status":
        return Handled(sessions.status(config.data_dir, now))
    if command.name == "cancel":
        return Handled(sessions.cancel(config.data_dir))
    if command.name == "progress":
        return Handled(_progress(config))
    if command.name == "topics":
        return Handled(_topics(config))
    return Handled(stats_module.stats(config.data_dir, now))


def handle_message(
    content: str,
    author_id: int,
    author_is_bot: bool,
    channel_id: int,
    config: Config,
    now: datetime,
) -> Handled | None:
    if author_is_bot or author_id != config.owner_id or channel_id != config.channel_id:
        return None
    command = parse_command(content)
    if command is None:
        return None
    try:
        handled = _dispatch(command, config, now)
    except Exception as error:
        # Type only: the message or traceback could carry paths, the token or user text.
        log.error("command %s failed with %s", command.name, type(error).__name__)
        return Handled(GENERIC_ERROR)
    return replace(handled, text=escape_mentions(handled.text))


def _describe_completed(result: SyncResult) -> str:
    if result.log_line:
        return f"Sync: {result.log_line}"
    if result.exit_code:
        return f"Sync failed with exit code {result.exit_code}; no log result was found."
    return f"Sync finished (exit code {result.exit_code}) but no log result was found."


def describe_sync(result: SyncResult, timeout_seconds: float) -> str:
    """The message posted after the sync; the session is already saved by then."""
    if result.status is SyncStatus.COMPLETED:
        text = _describe_completed(result)
    elif result.status is SyncStatus.TIMED_OUT:
        text = f"Sync timed out after {timeout_seconds:g} seconds. Session saved."
    elif result.status is SyncStatus.BUSY:
        text = "A sync is already running, so this one was skipped. Session saved."
    elif result.status is SyncStatus.SCRIPT_MISSING:
        text = "Sync script not found. Session saved."
    else:
        text = "Sync could not be started. Session saved."
    return escape_mentions(text)
