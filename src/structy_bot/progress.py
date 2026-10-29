import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from structy_bot.modules import Module

# Same names update_readme.py skips.
IGNORED_DIRS = frozenset({"__pycache__", "venv", ".venv", "node_modules", "env", "build", "dist"})


class Status(Enum):
    DONE = "done"
    IN_PROGRESS = "in progress"
    NOT_STARTED = "not started"


@dataclass(frozen=True)
class ModuleProgress:
    name: str
    files_in_repo: int
    solved_before_repo: int
    total_coding_problems: int | None
    status: Status

    @property
    def solved(self) -> int:
        return self.files_in_repo + self.solved_before_repo


def count_solutions(hub_path: Path, folder: str | None) -> int:
    if folder is None:
        return 0
    root, hub = (hub_path / folder).resolve(), hub_path.resolve()
    # A link inside the hub must not make the bot count files elsewhere.
    if not root.is_dir() or not root.is_relative_to(hub):
        return 0
    total = 0
    for _dir, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        total += sum(1 for name in files if name.endswith(".py"))
    return total


def _status(solved: int, total: int | None) -> Status:
    if total is not None and solved >= total:
        return Status.DONE
    return Status.IN_PROGRESS if solved > 0 else Status.NOT_STARTED


def compute_progress(modules: Iterable[Module], hub_path: Path) -> tuple[ModuleProgress, ...]:
    result = []
    for module in modules:
        files = count_solutions(hub_path, module.folder)
        solved = files + module.solved_before_repo
        total = module.total_coding_problems
        result.append(
            ModuleProgress(module.name, files, module.solved_before_repo, total,
                           _status(solved, total))
        )  # fmt: skip
    return tuple(result)


def _line(item: ModuleProgress) -> str:
    if item.total_coding_problems is None:
        detail = f"{item.solved} solved" if item.solved else "not started"
        return f"{item.name}: {detail}"
    if item.status is Status.NOT_STARTED:
        return f"{item.name}: not started"
    shown = min(item.solved, item.total_coding_problems)
    return f"{item.name}: {shown}/{item.total_coding_problems} {item.status.value}"


def format_progress(items: Sequence[ModuleProgress]) -> str:
    counts = {s: sum(1 for i in items if i.status is s) for s in Status}
    # Integer arithmetic so halves round up (Python's round() rounds half to even).
    percent = (200 * counts[Status.DONE] + len(items)) // (2 * len(items)) if items else 0
    summary = (
        f"{counts[Status.DONE]} done, {counts[Status.IN_PROGRESS]} in progress, "
        f"{counts[Status.NOT_STARTED]} not started ({percent}% of modules done)"
    )
    return "\n".join([summary, *map(_line, items)])


def split_message(text: str, limit: int = 2000) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if current and len(current) + 1 + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    chunks.append(current)
    return chunks
