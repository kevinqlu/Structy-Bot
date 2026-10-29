from pathlib import Path

import pytest

from structy_bot import bot
from structy_bot.config import Config
from structy_bot.instance_lock import InstanceLockError, acquire_instance_lock

# Assumption: within one process, Windows byte-range locks taken through a second
# handle on the same file fail, so a second acquire is testable without a subprocess.


def test_second_acquire_on_same_dir_fails_naming_the_lock_file(tmp_path: Path) -> None:
    first = acquire_instance_lock(tmp_path / "data")
    try:
        with pytest.raises(InstanceLockError) as raised:
            acquire_instance_lock(tmp_path / "data")
        assert "bot.lock" in str(raised.value) and "already running" in str(raised.value)
    finally:
        first.close()


def test_acquire_works_again_after_the_first_handle_is_closed(tmp_path: Path) -> None:
    acquire_instance_lock(tmp_path).close()
    acquire_instance_lock(tmp_path).close()


def test_different_data_dirs_do_not_conflict(tmp_path: Path) -> None:
    one, two = acquire_instance_lock(tmp_path / "a"), acquire_instance_lock(tmp_path / "b")
    one.close()
    two.close()


def test_main_exits_1_with_message_when_lock_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = Config("tok", 1, 2, tmp_path / "s.ps1", tmp_path / "s.log", tmp_path,
                    tmp_path / "m.json", tmp_path / "data", 120, 6)
    monkeypatch.setattr(bot, "load_or_exit", lambda: config)
    monkeypatch.setattr(bot, "create_client", lambda c: pytest.fail("must not create a client"))
    held = acquire_instance_lock(config.data_dir)
    try:
        with pytest.raises(SystemExit) as raised:
            bot.main()
    finally:
        held.close()
    assert raised.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("Error: ") and "already running" in err
