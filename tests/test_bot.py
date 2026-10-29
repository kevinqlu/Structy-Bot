import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import discord
import pytest

from structy_bot import storage
from structy_bot.bot import NO_MENTIONS, StructyClient, create_client
from structy_bot.config import Config
from structy_bot.storage import CurrentSession
from structy_bot.sync import SyncResult, SyncRunner, SyncStatus

OWNER = 111
CHANNEL = 222


def make_config(tmp_path: Path) -> Config:
    return Config("tok", OWNER, CHANNEL, tmp_path / "s.ps1", tmp_path / "s.log", tmp_path,
                  tmp_path / "modules.json", tmp_path / "data", 120, 6)


class FakeChannel:
    def __init__(self, channel_id: int = CHANNEL) -> None:
        self.id = channel_id
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def send(self, text: str, **kwargs: Any) -> None:
        self.sent.append((text, kwargs))


def fake_message(content: str, author_id: int = OWNER, channel: FakeChannel | None = None) -> Any:
    return SimpleNamespace(
        content=content,
        author=SimpleNamespace(id=author_id, bot=False),
        channel=channel or FakeChannel(),
    )


def test_no_mentions_constant() -> None:
    assert NO_MENTIONS.everyone is False
    assert NO_MENTIONS.users is False and NO_MENTIONS.roles is False
    assert NO_MENTIONS.replied_user is False


def test_create_client_enables_message_content_without_connecting(tmp_path: Path) -> None:
    client = create_client(make_config(tmp_path))
    assert isinstance(client, discord.Client)
    assert client.intents.message_content is True
    assert not client.is_ready()


def test_owner_command_is_sent_with_no_mentions(tmp_path: Path) -> None:
    client = create_client(make_config(tmp_path))
    message = fake_message("!status")
    asyncio.run(client.process_message(message))
    [(text, kwargs)] = message.channel.sent
    assert "No session" in text
    assert kwargs == {"allowed_mentions": NO_MENTIONS}


def test_non_owner_message_gets_no_reply(tmp_path: Path) -> None:
    client = create_client(make_config(tmp_path))
    message = fake_message("!status", author_id=999)
    asyncio.run(client.process_message(message))
    assert message.channel.sent == []


def test_wrong_channel_gets_no_reply(tmp_path: Path) -> None:
    client = create_client(make_config(tmp_path))
    message = fake_message("!status", channel=FakeChannel(333))
    asyncio.run(client.process_message(message))
    assert message.channel.sent == []


def test_messages_are_processed_in_arrival_order(tmp_path: Path) -> None:
    client = create_client(make_config(tmp_path))
    first, second = fake_message("!status"), fake_message("!stats")
    channel = FakeChannel()
    first.channel = second.channel = channel

    async def run() -> None:
        await asyncio.gather(client.process_message(first), client.process_message(second))

    asyncio.run(run())
    assert "No session" in channel.sent[0][0] and "sessions" in channel.sent[1][0]


def test_startup_posts_corrupt_session_note_and_reconciles(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config.data_dir.mkdir()
    (config.data_dir / "current_session.json").write_text("{broken", encoding="utf-8")
    client: StructyClient = create_client(config)
    channel = FakeChannel()
    client.get_channel = lambda channel_id: channel  # type: ignore[method-assign]
    asyncio.run(client.on_ready())
    [(text, kwargs)] = channel.sent
    assert "unreadable" in text and kwargs == {"allowed_mentions": NO_MENTIONS}
    assert not (config.data_dir / "current_session.json").exists()


def test_startup_warns_when_channel_is_not_visible(
    tmp_path: Path, caplog: Any
) -> None:
    client = create_client(make_config(tmp_path))
    client.get_channel = lambda channel_id: None  # type: ignore[method-assign]
    asyncio.run(client.on_ready())
    assert any(r.levelname == "WARNING" for r in caplog.records)


# Slice 9: the sync wired into !end

SYNC_OK = SyncResult(SyncStatus.COMPLETED, 0, "No change")


class FakeRunner:
    def __init__(self, result: SyncResult = SYNC_OK, hold: asyncio.Event | None = None) -> None:
        self.result = result
        self.hold = hold
        self.calls = 0
        self.started = asyncio.Event()
        self.seen_records: list[str] = []
        self.data_dir: Path | None = None
        self.error: Exception | None = None

    async def run(self) -> SyncResult:
        self.calls += 1
        if self.data_dir is not None:
            path = self.data_dir / "sessions.jsonl"
            self.seen_records.append(path.read_text(encoding="utf-8") if path.exists() else "")
        self.started.set()
        if self.hold is not None:
            await self.hold.wait()
        if self.error is not None:
            raise self.error
        return self.result


def make_client(tmp_path: Path, runner: FakeRunner) -> StructyClient:
    config = make_config(tmp_path)
    runner.data_dir = config.data_dir
    return StructyClient(config, discord.Intents.default(), runner)  # type: ignore[arg-type]


def start_session(client: StructyClient, minutes_ago: float) -> None:
    start = datetime.now().astimezone() - timedelta(minutes=minutes_ago)
    storage.write_current_session(client.config.data_dir, CurrentSession(OWNER, "Hashing", start))


def run_messages(client: StructyClient, *contents: str) -> FakeChannel:
    channel = FakeChannel()

    async def go() -> None:
        for content in contents:
            await client.process_message(fake_message(content, channel=channel))

    asyncio.run(go())
    return channel


def test_end_sends_recorded_reply_then_runs_sync_and_posts_log_line(tmp_path: Path) -> None:
    runner = FakeRunner(SyncResult(SyncStatus.COMPLETED, 0, "Pushed README update"))
    client = make_client(tmp_path, runner)
    start_session(client, 30)
    channel = run_messages(client, "!end")
    assert runner.calls == 1
    [(first, _), (second, _)] = channel.sent
    assert "Hashing" in first and "Pushed README update" not in first
    assert "Pushed README update" in second
    assert all(kwargs == {"allowed_mentions": NO_MENTIONS} for _, kwargs in channel.sent)


def test_record_is_on_disk_at_the_moment_run_is_called(tmp_path: Path) -> None:
    runner = FakeRunner()
    client = make_client(tmp_path, runner)
    start_session(client, 30)
    run_messages(client, "!end")
    [seen] = runner.seen_records
    assert '"topic": "Hashing"' in seen and seen.count("\n") == 1


@pytest.mark.parametrize(
    "status",
    [SyncStatus.TIMED_OUT, SyncStatus.SCRIPT_MISSING, SyncStatus.START_FAILED, SyncStatus.BUSY],
)
def test_failed_sync_leaves_record_and_says_session_saved(
    tmp_path: Path, status: SyncStatus
) -> None:
    client = make_client(tmp_path, FakeRunner(SyncResult(status)))
    start_session(client, 30)
    channel = run_messages(client, "!end")
    records, _ = storage.read_records(client.config.data_dir)
    assert len(records) == 1
    assert "saved" in channel.sent[1][0].lower()


def test_completed_without_log_line_shows_exit_code(tmp_path: Path) -> None:
    client = make_client(tmp_path, FakeRunner(SyncResult(SyncStatus.COMPLETED, 3, None)))
    start_session(client, 30)
    channel = run_messages(client, "!end")
    assert "3" in channel.sent[1][0]


def test_under_one_minute_end_never_runs_sync(tmp_path: Path) -> None:
    runner = FakeRunner()
    client = make_client(tmp_path, runner)
    start_session(client, 0.2)
    channel = run_messages(client, "!end")
    assert runner.calls == 0 and len(channel.sent) == 1


def test_end_without_session_never_runs_sync(tmp_path: Path) -> None:
    runner = FakeRunner()
    client = make_client(tmp_path, runner)
    channel = run_messages(client, "!end")
    assert runner.calls == 0 and len(channel.sent) == 1


def test_end_with_extra_args_never_runs_sync(tmp_path: Path) -> None:
    runner = FakeRunner()
    client = make_client(tmp_path, runner)
    start_session(client, 30)
    channel = run_messages(client, "!end foo")
    assert runner.calls == 0 and len(channel.sent) == 1
    assert storage.read_current_session(client.config.data_dir)[0] is not None


def test_non_owner_end_never_runs_sync(tmp_path: Path) -> None:
    runner = FakeRunner()
    client = make_client(tmp_path, runner)
    start_session(client, 30)
    channel = FakeChannel()
    asyncio.run(client.process_message(fake_message("!end", author_id=999, channel=channel)))
    assert runner.calls == 0 and channel.sent == []


def test_second_end_during_held_sync_starts_no_second_sync(tmp_path: Path) -> None:
    hold = asyncio.Event()
    runner = FakeRunner(hold=hold)
    client = make_client(tmp_path, runner)
    start_session(client, 30)
    channel = FakeChannel()

    async def go() -> None:
        first = asyncio.create_task(client.process_message(fake_message("!end", channel=channel)))
        await runner.started.wait()
        await client.process_message(fake_message("!end", channel=channel))
        hold.set()
        await first

    asyncio.run(go())
    assert runner.calls == 1
    assert "No session" in channel.sent[1][0]


def test_status_is_answered_while_sync_is_held_open(tmp_path: Path) -> None:
    hold = asyncio.Event()
    runner = FakeRunner(hold=hold)
    client = make_client(tmp_path, runner)
    start_session(client, 30)
    channel = FakeChannel()
    sent_before_release: list[str] = []

    async def go() -> None:
        first = asyncio.create_task(client.process_message(fake_message("!end", channel=channel)))
        await runner.started.wait()
        await client.process_message(fake_message("!status", channel=channel))
        sent_before_release.extend(text for text, _ in channel.sent)
        hold.set()
        await first

    asyncio.run(go())
    assert len(sent_before_release) == 2 and "No session" in sent_before_release[1]
    assert "No change" in channel.sent[2][0]


def test_runner_exception_gives_generic_message_and_bot_keeps_working(
    tmp_path: Path, caplog: Any
) -> None:
    runner = FakeRunner()
    runner.error = RuntimeError("secret-path C:\\x")
    client = make_client(tmp_path, runner)
    start_session(client, 30)
    channel = run_messages(client, "!end", "!status")
    assert len(channel.sent) == 3
    assert "saved" in channel.sent[1][0].lower() and "secret-path" not in channel.sent[1][0]
    assert "No session" in channel.sent[2][0]
    assert "secret-path" not in caplog.text and "RuntimeError" in caplog.text


def test_everyone_in_log_line_is_escaped_in_second_message(tmp_path: Path) -> None:
    result = SyncResult(SyncStatus.COMPLETED, 0, "ERROR: @everyone")
    client = make_client(tmp_path, FakeRunner(result))
    start_session(client, 30)
    channel = run_messages(client, "!end")
    assert "@everyone" not in channel.sent[1][0]
    assert channel.sent[1][1] == {"allowed_mentions": NO_MENTIONS}


def test_create_client_builds_runner_from_config(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    runner = create_client(config).sync_runner
    assert isinstance(runner, SyncRunner)
    assert (runner.script_path, runner.log_path, runner.timeout_seconds) == (
        config.sync_script_path, config.sync_log_path, 120)


# Slice 10: first send failing must not skip the sync; long replies are chunked


class FailFirstChannel(FakeChannel):
    failed = False

    async def send(self, text: str, **kwargs: Any) -> None:
        if not self.failed:
            self.failed = True
            raise RuntimeError("discord down")
        await super().send(text, **kwargs)


def test_sync_still_runs_when_the_first_send_raises(tmp_path: Path) -> None:
    runner = FakeRunner()
    client = make_client(tmp_path, runner)
    start_session(client, 30)
    channel = FailFirstChannel()
    asyncio.run(client.process_message(fake_message("!end", channel=channel)))
    assert runner.calls == 1
    records, _ = storage.read_records(client.config.data_dir)
    assert len(records) == 1


def test_long_progress_reply_is_split_into_chunks_with_no_mentions(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    mods = [{"name": f"Module {i} " + "x" * 90, "total_coding_problems": 500} for i in range(60)]
    config.modules_path.write_text(json.dumps({"modules": mods}), encoding="utf-8")
    client = create_client(config)
    channel = run_messages(client, "!progress")
    assert len(channel.sent) > 1
    assert all(len(text) <= 2000 for text, _ in channel.sent)
    assert all(kwargs == {"allowed_mentions": NO_MENTIONS} for _, kwargs in channel.sent)


# Slice 13b: startup robustness


class RaisingChannel(FakeChannel):
    async def send(self, text: str, **kwargs: Any) -> None:
        raise RuntimeError("discord down")


@pytest.mark.parametrize("channel", [RaisingChannel(), None], ids=["send-raises", "no-channel"])
def test_unsent_corrupt_note_is_kept_and_prepended_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, channel: Any
) -> None:
    config = make_config(tmp_path)
    config.data_dir.mkdir()
    (config.data_dir / "current_session.json").write_text("{broken", encoding="utf-8")
    client = create_client(config)
    monkeypatch.setattr(client, "get_channel", lambda channel_id: channel)
    reconciled: list[Path] = []
    real = storage.reconcile_startup
    monkeypatch.setattr(
        storage, "reconcile_startup", lambda d: reconciled.append(d) or real(d)
    )
    reply = FakeChannel()

    async def go() -> None:
        await client.on_ready()
        await client.process_message(fake_message("!status", channel=reply))
        await client.process_message(fake_message("!status", channel=reply))

    asyncio.run(go())
    assert reconciled == [config.data_dir]
    first, second = reply.sent[0][0], reply.sent[1][0]
    assert "unreadable" in first and "No session" in first
    assert "unreadable" not in second and "No session" in second


def test_startup_reconciles_already_logged_session_through_the_bot(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    start = datetime.now().astimezone() - timedelta(hours=1)
    storage.write_current_session(config.data_dir, CurrentSession(OWNER, "Hashing", start))
    record = storage.SessionRecord(OWNER, "Hashing", start, start + timedelta(minutes=30),
                                   1800, 1800, False)
    storage.append_record(config.data_dir, record)
    history = config.data_dir / "sessions.jsonl"
    before = history.read_bytes()
    client = create_client(config)
    client.get_channel = lambda channel_id: FakeChannel()  # type: ignore[method-assign]

    async def twice() -> None:
        await client.on_ready()
        await client.on_ready()

    asyncio.run(twice())
    assert not (config.data_dir / "current_session.json").exists()
    assert history.read_bytes() == before
