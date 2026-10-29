import pytest

from structy_bot.modules import Module
from structy_bot.topics import TopicKind, TopicMatch, clean_free_text_topic, resolve_topic

NAMES = [
    "Binary Search", "Binary Tree I", "Binary Tree II",
    "Linked List I", "Linked List II", "Graph I", "Graph II",
]
MODULES = tuple(Module(name, None, None, 0) for name in NAMES)


def by_name(*names: str) -> tuple[Module, ...]:
    return tuple(m for m in MODULES if m.name in names)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("linked-list-ii", "Linked List II"),
        ("Binary Tree I", "Binary Tree I"),
        ("binary tree i", "Binary Tree I"),
        ("BINARY_TREE_II", "Binary Tree II"),
        ("LinkedListII", "Linked List II"),
        ("  linked   list  i ", "Linked List I"),
        ("binary-s", "Binary Search"),
        ("linkedlisti", "Linked List I"),
    ],
)
def test_matched(text: str, expected: str) -> None:
    assert resolve_topic(text, MODULES) == TopicMatch(TopicKind.MATCHED, by_name(expected)[0], ())


def test_ambiguous_lists_candidates_in_file_order() -> None:
    match = resolve_topic("binary", MODULES)
    assert match.kind is TopicKind.AMBIGUOUS
    assert match.module is None
    assert match.candidates == by_name("Binary Search", "Binary Tree I", "Binary Tree II")


def test_ambiguous_graph() -> None:
    match = resolve_topic("graph", MODULES)
    assert match.kind is TopicKind.AMBIGUOUS
    assert match.candidates == by_name("Graph I", "Graph II")


def test_unknown() -> None:
    assert resolve_topic("heap", MODULES) == TopicMatch(TopicKind.UNKNOWN, None, ())


@pytest.mark.parametrize("text", ["", "   ", "--", " _ - ", "\t"])
def test_empty(text: str) -> None:
    assert resolve_topic(text, MODULES) == TopicMatch(TopicKind.EMPTY, None, ())


def test_matched_module_is_the_canonical_object_not_user_text() -> None:
    match = resolve_topic("@everyone linked-list-ii"[10:], MODULES)
    assert match.module is MODULES[4]
    assert match.module is not None and match.module.name == "Linked List II"
    assert resolve_topic("@everyone", MODULES).module is None


def test_longer_than_any_name_is_unknown() -> None:
    assert resolve_topic("binary tree iii", MODULES).kind is TopicKind.UNKNOWN


def test_no_modules_means_unknown() -> None:
    assert resolve_topic("anything", ()).kind is TopicKind.UNKNOWN


def test_topic_match_is_frozen() -> None:
    with pytest.raises(AttributeError):
        resolve_topic("heap", MODULES).kind = TopicKind.EMPTY  # type: ignore[misc]


def test_free_text_collapses_whitespace_and_strips() -> None:
    assert clean_free_text_topic("  two\t\n  words   here ") == "two words here"


def test_free_text_removes_control_characters() -> None:
    assert clean_free_text_topic("a\x00b\x07c\x1b[0m") == "abc[0m"
    assert clean_free_text_topic("a​b‮c") == "abc"  # zero-width, bidi override


@pytest.mark.parametrize("text", ["", "   ", "\x00\x01", "​ \t"])
def test_free_text_empty_is_none(text: str) -> None:
    assert clean_free_text_topic(text) is None


def test_free_text_caps_at_40() -> None:
    result = clean_free_text_topic("x" * 100)
    assert result == "x" * 40


def test_free_text_cap_then_strips_trailing_space() -> None:
    text = "a" * 39 + " " + "b" * 10
    assert clean_free_text_topic(text) == "a" * 39


def test_free_text_exactly_40_is_kept() -> None:
    assert clean_free_text_topic("y" * 40) == "y" * 40


def test_free_text_does_not_escape_mentions() -> None:
    assert clean_free_text_topic("@everyone") == "@everyone"
    assert clean_free_text_topic("<@123> @here") == "<@123> @here"
