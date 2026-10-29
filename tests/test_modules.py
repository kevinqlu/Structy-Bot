import json
from pathlib import Path
from typing import Any

import pytest

from structy_bot.modules import Module, ModulesError, load_modules, normalize_name

VALID = {
    "modules": [
        {"name": "Hashing", "folder": "Hashing",
         "total_coding_problems": 8, "solved_before_repo": 8},
        {"name": "Linked List I", "folder": "Linked-List-I",
         "total_coding_problems": 11, "solved_before_repo": 8},
        {"name": "Graph I", "folder": None,
         "total_coding_problems": None, "solved_before_repo": 0},
    ]
}


def write(tmp_path: Path, content: Any) -> Path:
    path = tmp_path / "modules.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path


def one(**entry: Any) -> dict[str, Any]:
    return {"modules": [{"name": "Hashing", **entry}]}


def assert_unusable(path: Path) -> ModulesError:
    with pytest.raises(ModulesError) as caught:
        load_modules(path)
    assert str(caught.value)
    assert "\n" not in str(caught.value)
    return caught.value


def test_normalize_name_lowercases_and_strips_separators() -> None:
    assert normalize_name("Binary Tree-I_") == "binarytreei"
    assert normalize_name("Array and String") == "arrayandstring"


def test_valid_file_preserves_order_nulls_and_values(tmp_path: Path) -> None:
    modules = load_modules(write(tmp_path, VALID))
    assert modules == (
        Module("Hashing", "Hashing", 8, 8),
        Module("Linked List I", "Linked-List-I", 11, 8),
        Module("Graph I", None, None, 0),
    )


def test_missing_optional_keys_default(tmp_path: Path) -> None:
    (module,) = load_modules(write(tmp_path, one()))
    assert module == Module("Hashing", None, None, 0)


def test_null_solved_before_repo_is_rejected(tmp_path: Path) -> None:
    assert_unusable(write(tmp_path, one(solved_before_repo=None)))


def test_module_is_frozen() -> None:
    with pytest.raises(AttributeError):
        Module("a", None, None, 0).name = "b"  # type: ignore[misc]


def test_missing_file(tmp_path: Path) -> None:
    error = assert_unusable(tmp_path / "nope.json")
    assert "nope.json" in str(error)


def test_unreadable_path_is_a_directory(tmp_path: Path) -> None:
    assert_unusable(tmp_path)


def test_invalid_json(tmp_path: Path) -> None:
    assert_unusable(write(tmp_path, '{"modules": [ {"name": '))


def test_invalid_utf8_bytes(tmp_path: Path) -> None:
    path = tmp_path / "modules.json"
    path.write_bytes(b'{"modules": []}\xff\xfe')
    assert_unusable(path)


@pytest.mark.parametrize(
    "content",
    [[], "text", 5, None, {}, {"modules": None}, {"modules": {}}, {"modules": "x"}, {"other": []}],
)
def test_wrong_top_level_shape(tmp_path: Path, content: Any) -> None:
    assert_unusable(write(tmp_path, content))


def test_empty_modules_list_is_malformed(tmp_path: Path) -> None:
    assert_unusable(write(tmp_path, {"modules": []}))


@pytest.mark.parametrize("name", ["--", " _ ", "-", "_-_ -"])
def test_name_that_normalizes_to_empty_is_rejected(tmp_path: Path, name: str) -> None:
    error = assert_unusable(write(tmp_path, {"modules": [{"name": name}]}))
    assert repr(name) in str(error)


@pytest.mark.parametrize("entry", ["Hashing", 3, None, ["Hashing"]])
def test_entry_not_an_object(tmp_path: Path, entry: Any) -> None:
    assert_unusable(write(tmp_path, {"modules": [entry]}))


@pytest.mark.parametrize("name", [None, 5, True, "", "   ", ["a"]])
def test_bad_name(tmp_path: Path, name: Any) -> None:
    assert_unusable(write(tmp_path, {"modules": [{"name": name}]}))


def test_name_key_missing(tmp_path: Path) -> None:
    assert_unusable(write(tmp_path, {"modules": [{"folder": "x"}]}))


def test_duplicate_names_after_normalization(tmp_path: Path) -> None:
    data = {"modules": [{"name": "Binary Tree I"}, {"name": "binary-tree-i"}]}
    assert_unusable(write(tmp_path, data))


@pytest.mark.parametrize("folder", [5, True, ["a"], {}])
def test_folder_wrong_type(tmp_path: Path, folder: Any) -> None:
    assert_unusable(write(tmp_path, one(folder=folder)))


@pytest.mark.parametrize(
    "folder", ["", "  ", "..", ".", "a/b", "a\\b", "C:\\x", "C:x", "/abs", "\\abs", "../x"]
)
def test_unsafe_folder_names_the_module(tmp_path: Path, folder: str) -> None:
    error = assert_unusable(write(tmp_path, one(folder=folder)))
    assert "Hashing" in str(error)


def test_plain_folder_with_dots_and_dashes_is_fine(tmp_path: Path) -> None:
    (module,) = load_modules(write(tmp_path, one(folder="Linked-List.I")))
    assert module.folder == "Linked-List.I"


@pytest.mark.parametrize("total", [0, -1, True, False, 1.5, 3.0, "8", [8]])
def test_bad_total(tmp_path: Path, total: Any) -> None:
    assert_unusable(write(tmp_path, one(total_coding_problems=total)))


@pytest.mark.parametrize("solved", [-1, True, False, 2.0, "3", [1]])
def test_bad_solved_before_repo(tmp_path: Path, solved: Any) -> None:
    assert_unusable(write(tmp_path, one(solved_before_repo=solved)))


def test_zero_solved_before_repo_is_allowed(tmp_path: Path) -> None:
    (module,) = load_modules(write(tmp_path, one(solved_before_repo=0)))
    assert module.solved_before_repo == 0


def test_bom_file_loads(tmp_path: Path) -> None:
    path = tmp_path / "modules.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(VALID).encode("utf-8"))
    assert len(load_modules(path)) == 3


def test_edits_are_seen_without_reload_step(tmp_path: Path) -> None:
    data = {"modules": [{"name": f"Module {i}"} for i in range(19)]}
    path = write(tmp_path, data)
    assert len(load_modules(path)) == 19
    data["modules"].append({"name": "Module 19"})
    write(tmp_path, data)
    modules = load_modules(path)
    assert len(modules) == 20
    assert modules[-1].name == "Module 19"


def test_file_that_becomes_malformed_is_rejected_next_call(tmp_path: Path) -> None:
    path = write(tmp_path, VALID)
    assert load_modules(path)
    write(tmp_path, '{"modules": [')
    assert_unusable(path)


def test_error_does_not_dump_file_contents(tmp_path: Path) -> None:
    data = {"modules": [{"name": "Hashing", "folder": "SECRET/x"}]}
    error = assert_unusable(write(tmp_path, data))
    assert "SECRET" not in str(error)
