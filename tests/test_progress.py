import os
import subprocess
from pathlib import Path

import pytest

from structy_bot.modules import Module
from structy_bot.progress import (
    ModuleProgress,
    Status,
    compute_progress,
    count_solutions,
    format_progress,
    split_message,
)

IGNORED_DIRS = {"__pycache__", "venv", ".venv", "node_modules", "env", "build", "dist"}


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


# count_solutions


def test_counts_py_files_recursively_and_ignores_other_files(tmp_path: Path) -> None:
    touch(tmp_path / "H" / "a.py")
    touch(tmp_path / "H" / "sub" / "deep" / "b.py")
    touch(tmp_path / "H" / "notes.md")
    touch(tmp_path / "H" / "c.pyc")
    touch(tmp_path / "Other" / "z.py")
    assert count_solutions(tmp_path, "H") == 2


@pytest.mark.parametrize("name", sorted(IGNORED_DIRS))
def test_ignored_dir_names_are_pruned_at_any_depth(tmp_path: Path, name: str) -> None:
    touch(tmp_path / "H" / "a.py")
    touch(tmp_path / "H" / name / "x.py")
    touch(tmp_path / "H" / "sub" / name / "y.py")
    touch(tmp_path / "H" / "sub" / name / "inner" / "w.py")
    assert count_solutions(tmp_path, "H") == 1


def test_other_dot_directories_are_not_pruned(tmp_path: Path) -> None:
    touch(tmp_path / "H" / ".hidden" / "a.py")
    assert count_solutions(tmp_path, "H") == 1


def test_ignored_name_above_the_module_folder_does_not_matter(tmp_path: Path) -> None:
    hub = tmp_path / "build" / "hub"
    touch(hub / "H" / "a.py")
    assert count_solutions(hub, "H") == 1


def test_missing_none_and_file_folders_count_zero(tmp_path: Path) -> None:
    touch(tmp_path / "afile")
    assert count_solutions(tmp_path, None) == 0
    assert count_solutions(tmp_path, "Nope") == 0
    assert count_solutions(tmp_path, "afile") == 0


def test_folder_escaping_the_hub_through_a_link_counts_zero(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    hub.mkdir()
    touch(tmp_path / "outside" / "a.py")
    link = hub / "Linked"
    try:
        os.symlink(tmp_path / "outside", link, target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            raise
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(tmp_path / "outside")],
            capture_output=True,
        )
        if made.returncode != 0:
            pytest.skip("OS refused to create a symlink or junction without privileges")
    assert count_solutions(hub, "Linked") == 0


# criterion 14: agree with update_readme.py's counting (copied logic; BASELINE = solved_before_repo)


def reference_total(hub: Path, folder: str, baseline: int) -> int:
    count = 0
    for _root, dirs, files in os.walk(hub / folder):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        count += sum(1 for f in files if f.endswith(".py"))
    return count + baseline


def test_counts_agree_with_the_readme_script_logic(tmp_path: Path) -> None:
    touch(tmp_path / "A" / "one.py")
    touch(tmp_path / "A" / "t" / "two.py")
    touch(tmp_path / "A" / "venv" / "lib" / "skip.py")
    touch(tmp_path / "B" / "x.py")
    touch(tmp_path / "B" / "__pycache__" / "x.py")
    touch(tmp_path / "B" / "readme.md")
    touch(tmp_path / "C" / "dist" / "d.py")
    modules = (
        Module("A", "A", 10, 3),
        Module("B", "B", None, 0),
        Module("C", "C", 5, 4),
    )
    got = compute_progress(modules, tmp_path)
    for result, folder, baseline in zip(got, "ABC", (3, 0, 4), strict=True):
        assert result.files_in_repo + result.solved_before_repo == reference_total(
            tmp_path, folder, baseline
        )


# compute_progress status


def progress(tmp_path: Path, files: int, before: int, total: int | None) -> ModuleProgress:
    for i in range(files):
        touch(tmp_path / "M" / f"{i}.py")
    return compute_progress((Module("M", "M", total, before),), tmp_path)[0]


def test_null_total_is_never_done(tmp_path: Path) -> None:
    assert progress(tmp_path, 50, 50, None).status is Status.IN_PROGRESS


@pytest.mark.parametrize(
    ("files", "before", "total", "status"),
    [
        (8, 0, 8, Status.DONE),
        (3, 5, 8, Status.DONE),
        (9, 0, 8, Status.DONE),
        (7, 0, 8, Status.IN_PROGRESS),
        (0, 0, 8, Status.NOT_STARTED),
        (0, 0, None, Status.NOT_STARTED),
    ],
)
def test_status_boundaries(
    tmp_path: Path, files: int, before: int, total: int | None, status: Status
) -> None:
    assert progress(tmp_path, files, before, total).status is status


def test_progress_carries_files_and_baseline(tmp_path: Path) -> None:
    item = progress(tmp_path, 2, 3, 11)
    assert (item.files_in_repo, item.solved_before_repo, item.total_coding_problems) == (2, 3, 11)


# format_progress


def item(name: str, files: int, before: int, total: int | None) -> ModuleProgress:
    solved = files + before
    if total is not None and solved >= total:
        status = Status.DONE
    else:
        status = Status.IN_PROGRESS if solved > 0 else Status.NOT_STARTED
    return ModuleProgress(name, files, before, total, status)


def test_module_lines_in_order_with_the_right_shape() -> None:
    text = format_progress(
        (
            item("Hashing", 0, 8, 8),
            item("Linked List II", 3, 0, 11),
            item("Graph I", 0, 0, None),
            item("Free", 2, 1, None),
        )
    )
    assert text.splitlines()[1:] == [
        "Hashing: 8/8 done",
        "Linked List II: 3/11 in progress",
        "Graph I: not started",
        "Free: 3 solved",
    ]


def test_display_never_exceeds_total() -> None:
    text = format_progress((item("Over", 4, 8, 11),))
    assert "Over: 11/11 done" in text and "12/11" not in text


@pytest.mark.parametrize(
    ("done", "total", "percent"), [(2, 3, "67%"), (1, 2, "50%"), (1, 8, "13%"), (0, 3, "0%")]
)
def test_summary_percent_rounds_halves_up(done: int, total: int, percent: str) -> None:
    items = tuple(item(f"M{i}", 0, 5, 5) for i in range(done)) + tuple(
        item(f"N{i}", 0, 0, 5) for i in range(total - done)
    )
    assert percent in format_progress(items).splitlines()[0]


def test_summary_counts() -> None:
    first = format_progress(
        (item("A", 0, 5, 5), item("B", 1, 0, 5), item("C", 0, 0, 5), item("D", 0, 0, 5))
    ).splitlines()[0]
    assert "1 done" in first and "1 in progress" in first and "2 not started" in first


# split_message


def test_split_message_boundaries() -> None:
    assert split_message("a" * 2000) == ["a" * 2000]
    assert split_message("a" * 2001) == ["a" * 2000, "a"]
    assert split_message("") == [""]
    assert split_message("a" * 1000 + "\n" + "b" * 1000) == ["a" * 1000, "b" * 1000]


def test_split_message_many_lines_and_overlong_line() -> None:
    text = "\n".join(f"line {i:04d}" for i in range(1000))
    chunks = split_message(text)
    assert all(len(c) <= 2000 for c in chunks) and len(chunks) > 1
    assert "\n".join(chunks) == text
    assert [len(c) for c in split_message("z" * 4500)] == [2000, 2000, 500]
    mixed = split_message("short\n" + "q" * 2500)
    assert all(len(c) <= 2000 for c in mixed)
    assert "".join(mixed).replace("\n", "") == "short" + "q" * 2500
