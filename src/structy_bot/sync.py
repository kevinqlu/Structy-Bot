import asyncio
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

TAIL_BYTES = 4096
MAX_LOG_CHARS = 300
STAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"
STAMP_LENGTH = 19
KILL_WAIT_SECONDS = 10
log = logging.getLogger(__name__)


class SyncStatus(Enum):
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    BUSY = "busy"
    SCRIPT_MISSING = "script_missing"
    START_FAILED = "start_failed"


@dataclass(frozen=True)
class SyncResult:
    status: SyncStatus
    exit_code: int | None = None
    log_line: str | None = None


def default_argv(script_path: Path) -> list[str]:
    return [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(script_path),
    ]  # fmt: skip


def _child_env() -> dict[str, str]:
    # The sync script and its git/python children have no use for the bot token.
    return {k: v for k, v in os.environ.items() if k.upper() != "DISCORD_TOKEN"}


def _last_log_line(log_path: Path) -> str | None:
    try:
        with log_path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - TAIL_BYTES))
            tail = handle.read()
    except OSError:
        return None
    lines = tail.decode("utf-8", errors="replace").lstrip("﻿").splitlines()
    return next((line for line in reversed(lines) if line.strip()), None)


def fresh_message(log_path: Path, started: datetime) -> str | None:
    """Message of the log's last line, only if stamped at or after `started`."""
    line = _last_log_line(log_path)
    if line is None:
        return None
    try:
        stamped = datetime.strptime(line[:STAMP_LENGTH], STAMP_FORMAT)
    except ValueError:
        return None
    if stamped < started:
        return None
    return line[STAMP_LENGTH:].strip()[:MAX_LOG_CHARS]


async def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    # A plain proc.kill() would orphan git/python children still holding index.lock.
    # Every wait is bounded so a hung taskkill cannot keep the runner's lock forever.
    try:
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(proc.pid), "/T", "/F",
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )  # fmt: skip
        failed = await asyncio.wait_for(killer.wait(), KILL_WAIT_SECONDS) != 0
    except (OSError, TimeoutError) as error:
        _log_kill_problem(error)
        failed = True
    if failed and proc.returncode is None:
        proc.kill()
    try:
        await asyncio.wait_for(proc.wait(), KILL_WAIT_SECONDS)
    except TimeoutError as error:
        _log_kill_problem(error)


def _log_kill_problem(error: Exception) -> None:
    log.warning("sync kill step failed with %s", type(error).__name__)


class SyncRunner:
    def __init__(
        self,
        script_path: Path,
        log_path: Path,
        timeout_seconds: float,
        *,
        argv_builder: Callable[[Path], list[str]] = default_argv,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.script_path = script_path
        self.log_path = log_path
        self.timeout_seconds = timeout_seconds
        self._argv_builder = argv_builder
        self._clock = clock
        self._lock = asyncio.Lock()

    async def run(self) -> SyncResult:
        if self._lock.locked():
            return SyncResult(SyncStatus.BUSY)
        async with self._lock:
            return await self._run_locked()

    async def _run_locked(self) -> SyncResult:
        if not self.script_path.is_file():
            return SyncResult(SyncStatus.SCRIPT_MISSING)
        started = self._clock().replace(microsecond=0)
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._argv_builder(self.script_path), env=_child_env(),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )  # fmt: skip
        except OSError:
            return SyncResult(SyncStatus.START_FAILED)
        try:
            await asyncio.wait_for(proc.wait(), self.timeout_seconds)
        except TimeoutError:
            await _kill_tree(proc)
            return SyncResult(SyncStatus.TIMED_OUT)
        except BaseException:
            await _kill_tree(proc)
            raise
        return SyncResult(
            SyncStatus.COMPLETED, proc.returncode, fresh_message(self.log_path, started)
        )
