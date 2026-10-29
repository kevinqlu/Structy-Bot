import builtins
import io
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import structy_bot.sessions as sessions_module
from structy_bot.config import Config
from structy_bot.handler import (
    Handled,
    ParsedCommand,
    describe_sync,
    handle_message,
    parse_command,
)
from structy_bot.storage import read_records
from structy_bot.sync import SyncResult, SyncStatus

PDT = timezone(timedelta(hours=-7))
NOW = datetime(2026, 10, 29, 9, 0, tzinfo=PDT)
OWNER = 111
CHANNEL = 222
SECRET = "super-secret-token-value"


def make_config(tmp_path: Path, data_dir: Any = None) -> Config:
    return Config(
        discord_token=SECRET,
        owner_id=OWNER,
        channel_id=CHANNEL,
        sync_script_path=tmp_path / "sync.ps1",
        sync_log_path=tmp_path / "sync.log",
        hub_path=tmp_path / "hub",
        modules_path=tmp_path / "modules.json",
        data_dir=data_dir if data_dir is not None else tmp_path / "data",
        sync_timeout_seconds=120,
        max_session_hours=6,
    )


def write_modules(config: Config) -> None:
    names = ["Hashing", "Linked List I", "Linked List II"]
    config.modules_path.write_text(
        json.dumps({"modules": [{"name": n} for n in names]}), encoding="utf-8"
    )


def send(config: Config, content: str, now: datetime = NOW) -> Handled:
    result = handle_message(content, OWNER, False, CHANNEL, config, now)
    assert result is not None
    return result


@pytest.fixture
def config(tmp_path: Path) -> Config:
    cfg = make_config(tmp_path)
    write_modules(cfg)
    return cfg


def session_file(config: Config) -> Path:
    return config.data_dir / "current_session.json"


# parse_command


@pytest.mark.parametrize(
    ("content", "name", "args"),
    [
        ("!study x", "study", "x"),
        ("!STUDY x", "study", "x"),
        ("!Study", "study", ""),
        ("!study", "study", ""),
        ("!study   linked  list \n", "study", "linked  list"),
        ("!end now", "end", "now"),
        ("!End", "end", ""),
        ("!status", "status", ""),
        ("!cancel", "cancel", ""),
        ("!stats", "stats", ""),
        ("!Progress", "progress", ""),
        ("!study\nhashing", "study", "hashing"),
    ],
)
def test_parse_recognises_commands(content: str, name: str, args: str) -> None:
    assert parse_command(content) == ParsedCommand(name, args)


@pytest.mark.parametrize(
    "content",
    ["!statsfoo", "!studying", "! study", "study x", "!unknown", "", "!", " !study"],
)
def test_parse_rejects_non_commands(content: str) -> None:
    assert parse_command(content) is None


# access rules (SPEC 5 rules 1-4, criterion 5)


class Untouchable:
    """A data_dir that fails the test if any storage code so much as looks at it."""

    def __truediv__(self, other: object) -> Any:
        raise AssertionError("storage was touched")

    def __getattr__(self, name: str) -> Any:
        raise AssertionError("storage was touched")


@pytest.mark.parametrize(
    ("author_id", "is_bot", "channel_id", "content"),
    [
        (OWNER, True, CHANNEL, "!study hashing"),  # bot
        (999, False, CHANNEL, "!study hashing"),  # not the owner
        (OWNER, False, 333, "!study hashing"),  # wrong channel
        (OWNER, False, 987654321, "!status"),  # DM-like channel id
        (999, True, 333, "!end"),
        (OWNER, False, CHANNEL, "hello there"),  # not a command
        (OWNER, False, CHANNEL, "! study hashing"),
    ],
)
def test_ignored_messages_return_none_and_touch_nothing(
    tmp_path: Path, author_id: int, is_bot: bool, channel_id: int, content: str
) -> None:
    cfg = make_config(tmp_path, data_dir=Untouchable())
    assert handle_message(content, author_id, is_bot, channel_id, cfg, NOW) is None


def test_ignored_message_leaves_real_data_dir_untouched(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    assert handle_message("!study x", 999, False, CHANNEL, cfg, NOW) is None
    assert not cfg.data_dir.exists()


# study


def test_study_starts_canonical_session(config: Config) -> None:
    result = send(config, "!study linked-list-i")
    assert "Linked List I" in result.text
    assert result.record_to_sync is None
    assert "Linked List I" in session_file(config).read_text(encoding="utf-8")


def test_study_ambiguous_is_refused(config: Config) -> None:
    result = send(config, "!study linked")
    assert "Linked List I" in result.text and "Linked List II" in result.text
    assert not session_file(config).exists()


def test_study_unknown_and_empty_are_refused(config: Config) -> None:
    assert "Hashing" in send(config, "!study heap").text
    assert "Hashing" in send(config, "!study").text
    assert not session_file(config).exists()


def test_study_while_running_is_refused(config: Config) -> None:
    send(config, "!study hashing")
    later = NOW + timedelta(minutes=10)
    result = send(config, "!study linked-list-i", later)
    assert "Hashing" in result.text and "10m" in result.text
    assert "Hashing" in session_file(config).read_text(encoding="utf-8")


def test_missing_modules_file_falls_back_and_shows_the_error(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)  # no modules.json written
    result = send(cfg, "!study my own topic")
    assert "my own topic" in session_file(cfg).read_text(encoding="utf-8")
    assert "modules.json" in result.text  # the one-line error is shown
    assert "fallback" in result.text.lower()


def test_malformed_modules_file_falls_back(config: Config) -> None:
    config.modules_path.write_text("{not json", encoding="utf-8")
    result = send(config, "!study anything")
    assert "not valid JSON" in result.text
    assert "anything" in session_file(config).read_text(encoding="utf-8")


def test_modules_are_reloaded_on_every_study(config: Config) -> None:
    assert "I don't know" in send(config, "!study newmod").text
    config.modules_path.write_text(json.dumps({"modules": [{"name": "NewMod"}]}), encoding="utf-8")
    assert "NewMod" in send(config, "!study newmod").text


# no-argument commands (criteria 18, 32)


@pytest.mark.parametrize("command", ["end", "status", "cancel", "stats"])
def test_no_argument_commands_refuse_extra_text_and_change_nothing(
    config: Config, command: str
) -> None:
    send(config, "!study hashing")
    before = session_file(config).read_bytes()
    result = send(config, f"!{command} foo", NOW + timedelta(hours=1))
    assert "no arguments" in result.text
    assert result.record_to_sync is None
    assert session_file(config).read_bytes() == before
    assert read_records(config.data_dir) == ([], 0)


# end / status / cancel / stats


def test_end_without_session(config: Config) -> None:
    result = send(config, "!end")
    assert "No session" in result.text
    assert result.record_to_sync is None


def test_end_records_and_carries_record_to_sync(config: Config) -> None:
    send(config, "!study hashing")
    result = send(config, "!end", NOW + timedelta(minutes=45))
    records, _ = read_records(config.data_dir)
    assert len(records) == 1
    assert result.record_to_sync == records[0]
    assert records[0].logged_seconds == 2700
    assert "45m" in result.text
    assert not session_file(config).exists()


def test_end_under_a_minute_has_no_record_to_sync(config: Config) -> None:
    send(config, "!study hashing")
    result = send(config, "!end", NOW + timedelta(seconds=40))
    assert result.record_to_sync is None
    assert "not logged" in result.text
    assert read_records(config.data_dir) == ([], 0)


def test_status_and_cancel(config: Config) -> None:
    assert "No session" in send(config, "!status").text
    send(config, "!study hashing")
    assert "Hashing" in send(config, "!status", NOW + timedelta(minutes=5)).text
    assert "Cancelled" in send(config, "!cancel").text
    assert not session_file(config).exists()
    assert read_records(config.data_dir) == ([], 0)


def test_stats_replies(config: Config) -> None:
    assert "No sessions in the last 7 days" in send(config, "!stats").text
    send(config, "!study hashing")
    send(config, "!end", NOW + timedelta(minutes=30))
    text = send(config, "!stats", NOW + timedelta(minutes=31)).text
    assert "Hashing: 30m" in text and "Streak: 1" in text


# case-insensitive commands (criterion 24)


def test_commands_are_case_insensitive(config: Config) -> None:
    assert "Hashing" in send(config, "!Study hashing").text
    assert "Hashing" in send(config, "!Status").text
    assert "Logged" in send(config, "!END", NOW + timedelta(minutes=5)).text


# error handling (SPEC 5 rule 8, criterion 33)


def test_unexpected_error_gives_generic_reply_and_next_call_works(
    config: Config, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*args: object) -> str:
        raise RuntimeError(f"secret detail {SECRET} C:\\private\\path")

    monkeypatch.setattr(sessions_module, "status", boom)
    with caplog.at_level(logging.ERROR):
        result = send(config, "!status")
    for leaked in ("secret detail", SECRET, "private", "Traceback", "RuntimeError"):
        assert leaked not in result.text
    assert result.record_to_sync is None
    logged = caplog.text
    assert "RuntimeError" in logged
    assert SECRET not in logged and "secret detail" not in logged and "Traceback" not in logged
    monkeypatch.undo()
    assert "No session" in send(config, "!status").text


def test_error_log_does_not_contain_message_content(
    config: Config, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*args: object) -> str:
        raise ValueError("x")

    monkeypatch.setattr(sessions_module, "study", boom)
    with caplog.at_level(logging.DEBUG):
        send(config, "!study my private topic")
    assert "private topic" not in caplog.text


# mention safety (criterion 6)


def test_mentions_in_fallback_topic_are_escaped_in_replies(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)  # fallback mode
    raw = "@everyone @here <@123> <@&456> <@!789>"
    started = send(cfg, f"!study {raw}").text
    status = send(cfg, "!status", NOW + timedelta(minutes=1)).text
    for text in (started, status):
        for ping in ("@everyone", "@here", "<@123>", "<@&456>", "<@!789>"):
            assert ping not in text
        assert "@\u200beveryone" in text and "@\u200bhere" in text and "<@\u200b123>" in text


# describe_sync (slice 9)


def _d(status: SyncStatus, code: int | None = None, line: str | None = None) -> str:
    return describe_sync(SyncResult(status, code, line), 120)


def test_describe_sync_shows_fresh_log_line_verbatim() -> None:
    line = "Skipped: repo has uncommitted changes"
    assert line in _d(SyncStatus.COMPLETED, 0, line)


def test_describe_sync_without_log_line_shows_exit_code() -> None:
    ok, bad = _d(SyncStatus.COMPLETED, 0), _d(SyncStatus.COMPLETED, 7)
    assert "no log result" in ok.lower() and "0" in ok
    assert "failed" in bad.lower() and "7" in bad


def test_describe_sync_timeout_mentions_seconds_and_saved() -> None:
    text = describe_sync(SyncResult(SyncStatus.TIMED_OUT), 90)
    assert "timed out" in text and "90" in text and "saved" in text


@pytest.mark.parametrize(
    ("status", "word"),
    [
        (SyncStatus.BUSY, "already running"),
        (SyncStatus.SCRIPT_MISSING, "not found"),
        (SyncStatus.START_FAILED, "could not be started"),
    ],
)
def test_describe_sync_other_statuses(status: SyncStatus, word: str) -> None:
    text = _d(status)
    assert word in text and "saved" in text


def test_describe_sync_escapes_mentions() -> None:
    assert "@everyone" not in _d(SyncStatus.COMPLETED, 0, "ERROR: @everyone <@123>")
    assert "<@123>" not in _d(SyncStatus.COMPLETED, 0, "ERROR: @everyone <@123>")


# Slice 10: !progress


def write_progress_modules(config: Config) -> None:
    mods = [
        {"name": "Hashing", "folder": "Hashing", "total_coding_problems": 8,
         "solved_before_repo": 8},
        {"name": "Graph I", "folder": None, "total_coding_problems": None},
    ]
    config.modules_path.write_text(json.dumps({"modules": mods}), encoding="utf-8")


def test_progress_replies_with_summary_and_modules(config: Config) -> None:
    write_progress_modules(config)
    text = send(config, "!progress").text
    assert "1 done" in text and "1 not started" in text and "50%" in text
    assert "Hashing: 8/8 done" in text and "Graph I: not started" in text


def test_progress_is_case_insensitive_and_reloads_modules(config: Config) -> None:
    write_progress_modules(config)
    assert "Hashing" in send(config, "!PROGRESS").text
    config.modules_path.write_text(json.dumps({"modules": [{"name": "Zed"}]}), encoding="utf-8")
    assert "Zed" in send(config, "!Progress").text


def test_progress_missing_modules_file_says_only_that(config: Config) -> None:
    config.modules_path.unlink()
    text = send(config, "!progress").text
    assert "cannot read" in text and "done" not in text and "\n" not in text.strip()


def test_progress_malformed_modules_file_says_only_that(config: Config) -> None:
    config.modules_path.write_text("{nope", encoding="utf-8")
    text = send(config, "!progress").text
    assert "not valid JSON" in text and "done" not in text and "\n" not in text.strip()


def test_progress_with_args_is_refused_and_changes_nothing(config: Config) -> None:
    write_progress_modules(config)
    result = send(config, "!progress foo")
    assert "no arguments" in result.text and not config.data_dir.exists()


def test_progress_from_wrong_user_or_channel_is_ignored(config: Config) -> None:
    assert handle_message("!progress", 999, False, CHANNEL, config, NOW) is None
    assert handle_message("!progress", OWNER, False, 333, config, NOW) is None


def test_progress_escapes_mentions_in_module_names(config: Config) -> None:
    config.modules_path.write_text(
        json.dumps({"modules": [{"name": "@everyone"}]}), encoding="utf-8"
    )
    assert "@everyone" not in send(config, "!progress").text


# criterion 23: nothing opens a file under the hub for writing


def test_no_command_opens_a_hub_file_for_writing(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_progress_modules(config)
    (config.hub_path / "Hashing").mkdir(parents=True)
    (config.hub_path / "Hashing" / "a.py").write_text("", encoding="utf-8")
    hub = config.hub_path.resolve()
    writes: list[str] = []
    real_builtin, real_io = builtins.open, io.open

    def spy(real: Any) -> Any:
        def wrapper(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            if isinstance(file, (str, os.PathLike)) and any(c in mode for c in "wax+"):
                writes.append(os.fspath(file))
            return real(file, mode, *args, **kwargs)

        return wrapper

    monkeypatch.setattr(builtins, "open", spy(real_builtin))
    monkeypatch.setattr(io, "open", spy(real_io))
    for command in ("!study hashing", "!status", "!stats", "!progress", "!end"):
        send(config, command, NOW + timedelta(hours=1))
    assert not [p for p in writes if Path(p).resolve().is_relative_to(hub)]
    assert any(Path(p).resolve().is_relative_to(config.data_dir.resolve()) for p in writes)
