import json
from pathlib import Path

import pytest

from structy_bot import topics_store
from structy_bot.modules import Module
from structy_bot.topics import TopicKind, resolve_topic
from structy_bot.topics_store import (
    CUSTOM_FILE,
    MAX_CUSTOM_TOPICS,
    AddResult,
    AddStatus,
    CustomTopics,
    add_custom_topic,
    effective_topics,
    read_custom_topics,
)

MODULES = (Module("Heap", None, None, 0), Module("Linked List I", "Linked-List-I", 11, 8))


def write_raw(data_dir: Path, content: bytes) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / CUSTOM_FILE
    path.write_bytes(content)
    return path


def write_topics(data_dir: Path, topics: list[str]) -> Path:
    return write_raw(data_dir, json.dumps({"topics": topics}).encode("utf-8"))


def stored(data_dir: Path) -> list[str]:
    return json.loads((data_dir / CUSTOM_FILE).read_text(encoding="utf-8"))["topics"]


MALFORMED = [
    pytest.param(b"{not json", id="bad-json"),
    pytest.param(b'{"topics": ["\xff\xfe"]}', id="invalid-utf8"),
    pytest.param(b'["A"]', id="array-top-level"),
    pytest.param(b"{}", id="missing-topics"),
    pytest.param(b'{"topics": "A"}', id="topics-not-list"),
    pytest.param(b'{"topics": ["A", 3]}', id="non-string-entry"),
    pytest.param(b'{"topics": [""]}', id="empty-entry"),
    pytest.param(b'{"topics": ["  \\t"]}', id="whitespace-entry"),
    pytest.param(b'{"topics": ["--"]}', id="separators-only-entry"),
    pytest.param(b'{"topics": ["Heap", "heap"]}', id="duplicate-after-normalize"),
]


# read

def test_read_missing_file(tmp_path: Path) -> None:
    assert read_custom_topics(tmp_path) == CustomTopics((), False)


def test_read_valid_preserves_order(tmp_path: Path) -> None:
    write_topics(tmp_path, ["Zeta", "Alpha", "Mid"])
    assert read_custom_topics(tmp_path) == CustomTopics(("Zeta", "Alpha", "Mid"), False)


def test_read_tolerates_bom(tmp_path: Path) -> None:
    write_raw(tmp_path, b'\xef\xbb\xbf{"topics": ["Heap"]}')
    assert read_custom_topics(tmp_path) == CustomTopics(("Heap",), False)


@pytest.mark.parametrize("content", MALFORMED)
def test_read_malformed(tmp_path: Path, content: bytes) -> None:
    write_raw(tmp_path, content)
    assert read_custom_topics(tmp_path) == CustomTopics((), True)


def test_read_does_not_enforce_caps(tmp_path: Path) -> None:
    names = [f"Topic {i} " + "x" * 50 for i in range(60)]
    write_topics(tmp_path, names)
    assert read_custom_topics(tmp_path) == CustomTopics(tuple(names), False)


# add

def test_first_add_creates_dir_and_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "nested" / "data"
    result = add_custom_topic(data_dir, "Tries", None)
    assert result == AddResult(AddStatus.ADDED, "Tries", None)
    assert stored(data_dir) == ["Tries"]


def test_add_appends_in_order(tmp_path: Path) -> None:
    for name in ("Tries", "Segment Tree", "Union Find"):
        assert add_custom_topic(tmp_path, name, MODULES).status is AddStatus.ADDED
    assert stored(tmp_path) == ["Tries", "Segment Tree", "Union Find"]


def test_add_cleans_name(tmp_path: Path) -> None:
    result = add_custom_topic(tmp_path, "  Seg\x00ment \t\n  Tree  ", None)
    assert result.name == "Segment Tree"
    long = add_custom_topic(tmp_path, "y" * 100, None)
    assert long.name == "y" * 40
    assert stored(tmp_path) == ["Segment Tree", "y" * 40]


def test_add_stores_mentions_raw(tmp_path: Path) -> None:
    # Escaping is a display concern; storage keeps the cleaned text as typed.
    result = add_custom_topic(tmp_path, "@everyone", None)
    assert result.name == "@everyone"
    assert stored(tmp_path) == ["@everyone"]


def test_add_non_ascii_round_trips(tmp_path: Path) -> None:
    add_custom_topic(tmp_path, "Graphes élégants 图", None)
    assert read_custom_topics(tmp_path).names == ("Graphes élégants 图",)


@pytest.mark.parametrize("raw", ["", "   ", "\x00\x01\x1b", "--", " _ - "])
def test_add_empty(tmp_path: Path, raw: str) -> None:
    assert add_custom_topic(tmp_path, raw, MODULES) == AddResult(AddStatus.EMPTY, None, None)
    assert not (tmp_path / CUSTOM_FILE).exists()


@pytest.mark.parametrize("raw", ["HEAP", "heap", "  he-ap "])
def test_add_duplicate_of_module(tmp_path: Path, raw: str) -> None:
    result = add_custom_topic(tmp_path, raw, MODULES)
    assert result == AddResult(AddStatus.DUPLICATE, None, "Heap")
    assert not (tmp_path / CUSTOM_FILE).exists()


@pytest.mark.parametrize("raw", ["linked-list-i", "linked list i", "LINKED_LIST_I"])
def test_add_duplicate_of_module_spacing(tmp_path: Path, raw: str) -> None:
    assert add_custom_topic(tmp_path, raw, MODULES) == AddResult(
        AddStatus.DUPLICATE, None, "Linked List I"
    )


def test_add_duplicate_of_custom_leaves_file_unchanged(tmp_path: Path) -> None:
    path = write_topics(tmp_path, ["Trie Node"])
    before = path.read_bytes()
    result = add_custom_topic(tmp_path, "trie-node", MODULES)
    assert result == AddResult(AddStatus.DUPLICATE, None, "Trie Node")
    assert path.read_bytes() == before


def test_add_limit_reached_leaves_file_unchanged(tmp_path: Path) -> None:
    path = write_topics(tmp_path, [f"Topic {i}" for i in range(MAX_CUSTOM_TOPICS)])
    before = path.read_bytes()
    assert add_custom_topic(tmp_path, "One More", MODULES) == AddResult(
        AddStatus.LIMIT_REACHED, None, None
    )
    assert path.read_bytes() == before


def test_fiftieth_add_succeeds(tmp_path: Path) -> None:
    write_topics(tmp_path, [f"Topic {i}" for i in range(MAX_CUSTOM_TOPICS - 1)])
    assert add_custom_topic(tmp_path, "Last One", MODULES).status is AddStatus.ADDED
    assert len(stored(tmp_path)) == MAX_CUSTOM_TOPICS


@pytest.mark.parametrize("content", MALFORMED)
def test_add_refuses_malformed_file_and_leaves_bytes(tmp_path: Path, content: bytes) -> None:
    path = write_raw(tmp_path, content)
    assert add_custom_topic(tmp_path, "Heap2", MODULES) == AddResult(
        AddStatus.MALFORMED_FILE, None, None
    )
    assert path.read_bytes() == content
    assert [p.name for p in tmp_path.iterdir()] == [CUSTOM_FILE]


def test_failed_replace_keeps_previous_file_and_leaves_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_topics(tmp_path, ["Existing"])
    before = path.read_bytes()

    def boom(src: object, dst: object) -> None:
        raise OSError("disk exploded")

    monkeypatch.setattr(topics_store.os, "replace", boom)
    with pytest.raises(OSError, match="disk exploded"):
        add_custom_topic(tmp_path, "New Topic", MODULES)
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == [CUSTOM_FILE]


# effective_topics

def test_effective_modules_then_custom() -> None:
    result = effective_topics(MODULES, ["Tries", "Zeta"])
    assert [m.name for m in result] == ["Heap", "Linked List I", "Tries", "Zeta"]


def test_effective_none_modules() -> None:
    assert [m.name for m in effective_topics(None, ["Tries"])] == ["Tries"]


def test_effective_module_wins_on_collision() -> None:
    result = effective_topics(MODULES, ["heap", "Tries"])
    assert [m.name for m in result] == ["Heap", "Linked List I", "Tries"]


def test_effective_custom_entries_are_bare_modules() -> None:
    assert effective_topics(None, ["Tries"]) == (Module("Tries", None, None, 0),)


def test_effective_empty_inputs() -> None:
    assert effective_topics(None, []) == ()
    assert effective_topics((), []) == ()


# round trip

def test_added_topics_resolve_for_study(tmp_path: Path) -> None:
    add_custom_topic(tmp_path, "Segment Tree", MODULES)
    add_custom_topic(tmp_path, "Union Find", MODULES)
    custom = read_custom_topics(tmp_path)
    assert not custom.malformed
    match = resolve_topic("segment-tree", effective_topics(MODULES, custom.names))
    assert match.kind is TopicKind.MATCHED
    assert match.module == Module("Segment Tree", None, None, 0)
    prefix = resolve_topic("union", effective_topics(None, custom.names))
    assert prefix.module is not None and prefix.module.name == "Union Find"
