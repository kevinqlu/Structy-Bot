import asyncio
import sys
import textwrap
import time
from datetime import datetime, timedelta
from pathlib import Path

from structy_bot.sync import SyncResult, SyncRunner, SyncStatus, default_argv

T0 = datetime(2026, 10, 29, 10, 40, 4, 700000)


def py_argv(path: Path) -> list[str]:
    return [sys.executable, str(path)]


def make_script(tmp_path: Path, body: str, name: str = "fake.py") -> Path:
    script = tmp_path / name
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return script


def runner(script: Path, log: Path, timeout: float = 10, clock=lambda: T0) -> SyncRunner:
    return SyncRunner(script, log, timeout, argv_builder=py_argv, clock=clock)


def run_sync(sync: SyncRunner) -> SyncResult:
    return asyncio.run(sync.run())


def noop_script(tmp_path: Path, code: int = 0) -> Path:
    return make_script(tmp_path, f"import sys\nsys.exit({code})\n")


def write_log(log: Path, *lines: str) -> None:
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def test_default_argv_is_fixed_list():
    assert default_argv(Path(r"C:\x\sync.ps1")) == [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", r"C:\x\sync.ps1",
    ]  # fmt: skip


def test_completed_run_returns_fresh_log_text(tmp_path):
    log = tmp_path / "sync.log"
    script = make_script(
        tmp_path,
        f"""
        from datetime import datetime
        with open({str(log)!r}, "a", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%Y-%m-%dT%H:%M:%S") + "  Pushed README update\\n")
        """,
    )
    result = run_sync(SyncRunner(script, log, 10, argv_builder=py_argv))
    assert result == SyncResult(SyncStatus.COMPLETED, 0, "Pushed README update")


def test_exit_code_reported(tmp_path):
    log = tmp_path / "sync.log"
    write_log(log, f"{stamp(T0)}  ERROR: boom")
    result = run_sync(runner(noop_script(tmp_path, 3), log))
    assert (result.status, result.exit_code) == (SyncStatus.COMPLETED, 3)
    assert result.log_line == "ERROR: boom"


def test_nonzero_exit_without_fresh_line(tmp_path):
    log = tmp_path / "sync.log"
    write_log(log, f"{stamp(T0 - timedelta(hours=1))}  No change")
    result = run_sync(runner(noop_script(tmp_path, 2), log))
    assert result == SyncResult(SyncStatus.COMPLETED, 2, None)


def test_same_second_is_fresh_and_earlier_second_is_stale(tmp_path):
    log = tmp_path / "sync.log"
    script = noop_script(tmp_path)
    write_log(log, f"{stamp(T0)}  No change")
    assert run_sync(runner(script, log)).log_line == "No change"
    write_log(log, f"{stamp(T0 - timedelta(seconds=1))}  No change")
    assert run_sync(runner(script, log)).log_line is None


def test_missing_log_file(tmp_path):
    result = run_sync(runner(noop_script(tmp_path), tmp_path / "nope.log"))
    assert result == SyncResult(SyncStatus.COMPLETED, 0, None)


def test_garbage_last_line(tmp_path):
    log = tmp_path / "sync.log"
    write_log(log, f"{stamp(T0)}  No change", "not a timestamp at all")
    assert run_sync(runner(noop_script(tmp_path), log)).log_line is None


def test_trailing_blank_lines_ignored(tmp_path):
    log = tmp_path / "sync.log"
    log.write_text(f"{stamp(T0)}  No change\n\n  \n\n", encoding="utf-8")
    assert run_sync(runner(noop_script(tmp_path), log)).log_line == "No change"


def test_bom_is_stripped(tmp_path):
    log = tmp_path / "sync.log"
    log.write_bytes(b"\xef\xbb\xbf" + f"{stamp(T0)}  No change\n".encode())
    assert run_sync(runner(noop_script(tmp_path), log)).log_line == "No change"


def test_long_message_capped_to_300(tmp_path):
    log = tmp_path / "sync.log"
    write_log(log, f"{stamp(T0)}  " + "x" * 1000)
    assert run_sync(runner(noop_script(tmp_path), log)).log_line == "x" * 300


def test_big_log_returns_last_line(tmp_path):
    log = tmp_path / "sync.log"
    old = f"{stamp(T0 - timedelta(days=1))}  No change\n"
    log.write_text(old * 50000 + f"{stamp(T0)}  Pushed README update\n", encoding="utf-8")
    assert run_sync(runner(noop_script(tmp_path), log)).log_line == "Pushed README update"


def test_script_missing_starts_no_process(tmp_path):
    marker = tmp_path / "marker"
    calls: list[Path] = []

    def spy(path: Path) -> list[str]:
        calls.append(path)
        return py_argv(path)

    sync = SyncRunner(tmp_path / "gone.py", tmp_path / "l.log", 5, argv_builder=spy)
    assert run_sync(sync) == SyncResult(SyncStatus.SCRIPT_MISSING, None, None)
    assert calls == [] and not marker.exists()


def test_timeout_returns_quickly_and_kills_process(tmp_path):
    pid_file = tmp_path / "pid"
    script = make_script(
        tmp_path,
        f"""
        import os, time
        open({str(pid_file)!r}, "w").write(str(os.getpid()))
        time.sleep(60)
        """,
    )
    began = time.monotonic()
    result = run_sync(runner(script, tmp_path / "l.log", timeout=1.0))
    assert result == SyncResult(SyncStatus.TIMED_OUT, None, None)
    assert time.monotonic() - began < 8
    assert not _pid_alive(int(pid_file.read_text()))


def _pid_alive(pid: int) -> bool:
    import subprocess

    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
    ).stdout
    return str(pid) in out


def test_timeout_kills_whole_process_tree(tmp_path):
    beat = tmp_path / "beat"
    child = make_script(
        tmp_path,
        f"""
        import time
        while True:
            open({str(beat)!r}, "w").write(str(time.time()))
            time.sleep(0.1)
        """,
        "child.py",
    )
    parent = make_script(
        tmp_path,
        f"""
        import subprocess, sys, time
        subprocess.Popen([sys.executable, {str(child)!r}])
        time.sleep(60)
        """,
    )
    result = run_sync(runner(parent, tmp_path / "l.log", timeout=1.5))
    assert result.status is SyncStatus.TIMED_OUT
    assert beat.exists()
    before = beat.read_text()
    time.sleep(1)
    assert beat.read_text() == before


def slow_script(tmp_path: Path, marker_dir: Path) -> Path:
    marker_dir.mkdir()
    return make_script(
        tmp_path,
        f"""
        import os, sys, time
        d = {str(marker_dir)!r}
        if os.listdir(d):
            sys.exit(99)
        open(os.path.join(d, "running"), "w").close()
        time.sleep(1)
        os.remove(os.path.join(d, "running"))
        """,
    )


def test_overlapping_runs_one_completes_one_busy(tmp_path):
    sync = runner(slow_script(tmp_path, tmp_path / "m"), tmp_path / "l.log")

    async def both():
        return await asyncio.gather(sync.run(), sync.run())

    results = asyncio.run(both())
    assert sorted(r.status.name for r in results) == ["BUSY", "COMPLETED"]
    completed = next(r for r in results if r.status is SyncStatus.COMPLETED)
    assert completed.exit_code == 0


def test_event_loop_keeps_ticking_during_sync(tmp_path):
    sync = runner(slow_script(tmp_path, tmp_path / "m"), tmp_path / "l.log")
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    async def main():
        task = asyncio.create_task(ticker())
        result = await sync.run()
        task.cancel()
        return result

    assert asyncio.run(main()).status is SyncStatus.COMPLETED
    assert ticks >= 10


def test_lock_released_after_timeout(tmp_path):
    hang = make_script(tmp_path, "import time\ntime.sleep(60)\n", "hang.py")
    log = tmp_path / "l.log"
    assert run_sync(runner(hang, log, timeout=0.5)).status is SyncStatus.TIMED_OUT

    async def twice():
        sync = runner(hang, log, timeout=0.5)
        first = await sync.run()
        sync.script_path = noop_script(tmp_path)
        return first, await sync.run()

    first, second = asyncio.run(twice())
    assert first.status is SyncStatus.TIMED_OUT
    assert second.status is SyncStatus.COMPLETED


def test_start_failed_and_lock_released(tmp_path):
    script = noop_script(tmp_path)
    builder_args = [[str(tmp_path / "no-such-executable.exe")], py_argv(script)]
    sync = SyncRunner(script, tmp_path / "l.log", 5, argv_builder=lambda p: builder_args.pop(0))

    async def twice():
        return await sync.run(), await sync.run()

    first, second = asyncio.run(twice())
    assert first == SyncResult(SyncStatus.START_FAILED, None, None)
    assert second.status is SyncStatus.COMPLETED


# Slice 13b: hardening


def test_child_does_not_inherit_discord_token_but_keeps_other_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "secret-token")
    monkeypatch.setenv("discord_token", "secret-lower")
    out = tmp_path / "env.txt"
    script = make_script(
        tmp_path,
        f"""
        import os
        names = [n.upper() for n in os.environ]
        open({str(out)!r}, "w").write(
            f"token={{'DISCORD_TOKEN' in names}} path={{'PATH' in names}}"
        )
        """,
    )
    result = run_sync(runner(script, tmp_path / "l.log"))
    assert result.status is SyncStatus.COMPLETED
    assert out.read_text() == "token=False path=True"


class HangingProcess:
    pid = 4242
    returncode = None

    async def wait(self) -> int:
        await asyncio.Event().wait()
        return 0

    def kill(self) -> None:
        pass


class QuickProcess:
    pid = 4243
    returncode = 0

    async def wait(self) -> int:
        return 0


def test_hung_kill_waits_are_bounded_and_lock_is_released(tmp_path, monkeypatch):
    import structy_bot.sync as sync_module

    monkeypatch.setattr(sync_module, "KILL_WAIT_SECONDS", 0.2, raising=False)
    calls = []

    async def fake_exec(*args, **kwargs):
        calls.append(args)
        # 1st: the sync process, 2nd: taskkill, 3rd: a later healthy sync
        return QuickProcess() if len(calls) == 3 else HangingProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    sync = runner(noop_script(tmp_path), tmp_path / "l.log", timeout=0.1)

    async def twice():
        began = time.monotonic()
        first = await sync.run()
        elapsed = time.monotonic() - began
        return first, elapsed, await sync.run()

    first, elapsed, second = asyncio.run(asyncio.wait_for(twice(), 5))
    assert first.status is SyncStatus.TIMED_OUT
    assert elapsed < 3
    assert second.status is SyncStatus.COMPLETED
