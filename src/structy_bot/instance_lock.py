import msvcrt
from pathlib import Path
from typing import BinaryIO

LOCK_FILE = "bot.lock"


class InstanceLockError(Exception):
    """Another bot instance already holds the data directory's lock."""


def acquire_instance_lock(data_dir: Path) -> BinaryIO:
    """Lock `bot.lock` for the life of the process; the caller keeps the handle open.

    The OS drops the lock when the process dies, so a stale file never blocks.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / LOCK_FILE
    handle = path.open("ab")
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        raise InstanceLockError(
            f"another instance is already running (lock held on {path})"
        ) from None
    return handle
