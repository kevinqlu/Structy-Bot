import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import structy_bot.topics_store as topics_store
from structy_bot.config import Config
from structy_bot.handler import GENERIC_ERROR, Handled, handle_message
from structy_bot.topics_store import CUSTOM_FILE

PDT = timezone(timedelta(hours=-7))
NOW = datetime(2026, 10, 29, 9, 0, tzinfo=PDT)
OWNER = 111
CHANNEL = 222
MODULE_NAMES = ["Hashing", "Linked List I", "Linked List II"]


def make_config(tmp_path: Path) -> Config:
    return Config(
        discord_token="token",
        owner_id=OWNER,
        channel_id=CHANNEL,
        sync_script_path=tmp_path / "sync.ps1",
        sync_log_path=tmp_path / "sync.log",
        hub_path=tmp_path / "hub",
        modules_path=tmp_path / "modules.json",
        data_dir=tmp_path / "data",
        sync_timeout_seconds=120,
        max_session_hours=6,
    )


def write_modules(config: Config, names: list[str] = MODULE_NAMES) -> None:
    entries = [{"name": n, "folder": None, "total_coding_problems": 8} for n in names]
    config.modules_path.write_text(json.dumps({"modules": entries}), encoding="utf-8")


def custom_path(config: Config) -> Path:
    return config.data_dir / CUSTOM_FILE


def write_custom(config: Config, names: list[str]) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    custom_path(config).write_text(json.dumps({"topics": names}), encoding="utf-8")


def send(config: Config, content: str) -> Handled:
    result = handle_message(content, OWNER, False, CHANNEL, config, NOW)
    assert result is not None
    return result


def stored_topic(config: Config) -> str:
    return json.loads((config.data_dir / "current_session.json").read_text("utf-8"))["topic"]


@pytest.fixture
def config(tmp_path: Path) -> Config:
    cfg = make_config(tmp_path)
    write_modules(cfg)
    return cfg


@pytest.fixture
def bare(tmp_path: Path) -> Config:
    return make_config(tmp_path)  # no modules.json, no custom topics


# !topics (criteria 36, 37)


def test_topics_lists_modules_in_order_then_custom_marked_added(config: Config) -> None:
    write_custom(config, ["Heap", "Trie"])
    text = send(config, "!topics").text
    lines = text.splitlines()
    order = ["Hashing", "Linked List I", "Linked List II", "Heap", "Trie"]
    positions = [text.index(n) for n in order]
    assert positions == sorted(positions)
    assert not any("(added)" in line for line in lines if "Hashing" in line)
    assert any("Heap" in line and "(added)" in line for line in lines)
    assert any("Trie" in line and "(added)" in line for line in lines)


def test_topics_without_any_topic_points_to_addtopic(bare: Config) -> None:
    text = send(bare, "!topics").text
    assert "!addtopic" in text and "free-text" in text.lower()
    assert "modules.json is missing or malformed" in text


def test_topics_with_modules_missing_shows_reason_first_and_lists_custom(bare: Config) -> None:
    write_custom(bare, ["Heap"])
    lines = send(bare, "!topics").text.splitlines()
    assert lines[0].startswith("modules.json is missing or malformed: ")
    assert any("Heap" in line and "(added)" in line for line in lines)


def test_topics_with_malformed_custom_file_notes_it_and_ignores_it(config: Config) -> None:
    config.data_dir.mkdir()
    custom_path(config).write_text("{nope", encoding="utf-8")
    text = send(config, "!topics").text
    assert "unreadable" in text and "ignor" in text
    assert "Hashing" in text and "(added)" not in text


def test_topics_is_read_only(config: Config) -> None:
    send(config, "!topics")
    assert not config.data_dir.exists()


def test_topics_lists_a_module_that_was_also_added_once(config: Config) -> None:
    send(config, "!addtopic Heap")
    write_modules(config, [*MODULE_NAMES, "heap"])
    text = send(config, "!topics").text
    assert text.lower().count("heap") == 1
    assert "(added)" not in text


# !addtopic (criteria 38, 41, 42)


def test_addtopic_then_study_uses_canonical_name_without_restart(config: Config) -> None:
    reply = send(config, "!addtopic  Heap ").text
    assert "Heap" in reply and "!study" in reply
    send(config, "!study heap")
    assert stored_topic(config) == "Heap"


def test_free_text_still_works_with_no_topics_but_not_after_one_addtopic(bare: Config) -> None:
    send(bare, "!study anything goes")
    assert stored_topic(bare) == "anything goes"
    (bare.data_dir / "current_session.json").unlink()
    send(bare, "!addtopic Heap")
    reply = send(bare, "!study anything goes").text
    assert not (bare.data_dir / "current_session.json").exists()
    assert "Heap" in reply and "!topics" in reply


def test_modules_reason_is_not_shown_in_validated_mode(bare: Config) -> None:
    send(bare, "!addtopic Heap")
    reply = send(bare, "!study heap").text
    assert "modules.json" not in reply and "fallback" not in reply.lower()


def test_fallback_lead_in_reads_like_progress(bare: Config) -> None:
    text = send(bare, "!study my topic").text
    assert text.splitlines()[0].startswith("modules.json is missing or malformed: ")
    assert "fallback" in text.lower()


def test_progress_is_unchanged_by_addtopic(config: Config) -> None:
    before = send(config, "!progress").text
    send(config, "!addtopic Heap")
    assert send(config, "!progress").text == before
    assert "Heap" not in before


@pytest.mark.parametrize("typed", ["heap", "  HEAP ", "h-e_a p", "Linked-List_i", "hashing"])
def test_duplicates_are_refused_naming_the_existing_topic(config: Config, typed: str) -> None:
    send(config, "!addtopic Heap")
    stored = custom_path(config).read_bytes()
    reply = send(config, f"!addtopic {typed}").text
    assert custom_path(config).read_bytes() == stored
    existing = {"heap": "Heap", "hashing": "Hashing"}.get(typed.strip().lower(), "")
    if existing:
        assert existing in reply
    assert "already" in reply


def test_duplicate_of_module_names_the_stored_module_not_raw_text(config: Config) -> None:
    reply = send(config, "!addtopic linked-list-i").text
    assert "Linked List I" in reply and "linked-list-i" not in reply
    assert not custom_path(config).exists()


@pytest.mark.parametrize("args", ["", "   ", "\x00", "---", "_ _"])
def test_empty_or_unusable_name_writes_nothing(config: Config, args: str) -> None:
    reply = send(config, f"!addtopic {args}").text
    assert not custom_path(config).exists()
    if not args.strip():
        assert "!addtopic <name>" in reply


def test_limit_of_50_is_enforced(config: Config) -> None:
    write_custom(config, [f"Topic {n}x" for n in range(50)])
    before = custom_path(config).read_bytes()
    reply = send(config, "!addtopic one more").text
    assert "50" in reply and "custom_topics.json" in reply
    assert custom_path(config).read_bytes() == before


def test_malformed_custom_file_is_left_byte_identical(config: Config) -> None:
    config.data_dir.mkdir()
    custom_path(config).write_bytes(b'{"topics": [1, ')
    reply = send(config, "!addtopic Heap").text
    assert "unreadable" in reply and "nothing was changed" in reply
    assert custom_path(config).read_bytes() == b'{"topics": [1, '


def test_write_failure_gives_generic_reply_and_keeps_old_file(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    send(config, "!addtopic Heap")
    before = custom_path(config).read_bytes()

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full at C:\\secret")

    monkeypatch.setattr(topics_store.os, "replace", boom)
    reply = send(config, "!addtopic Trie")
    assert reply.text == GENERIC_ERROR
    assert custom_path(config).read_bytes() == before
    monkeypatch.undo()
    assert "Heap" in send(config, "!topics").text


def test_module_added_later_wins_over_custom_topic(config: Config) -> None:
    send(config, "!addtopic Heap")
    write_modules(config, [*MODULE_NAMES, "Heap"])
    send(config, "!study heap")
    assert stored_topic(config) == "Heap"


# access, parsing, escaping (criteria 43, 44)


def test_topics_refuses_extra_text_and_changes_nothing(config: Config) -> None:
    reply = send(config, "!topics foo").text
    assert "takes no arguments" in reply
    assert not config.data_dir.exists()


@pytest.mark.parametrize("content", ["! topics", "! addtopic x", "!topicsfoo", "!addtopicx y"])
def test_non_commands_get_no_reply(config: Config, content: str) -> None:
    assert handle_message(content, OWNER, False, CHANNEL, config, NOW) is None


@pytest.mark.parametrize(
    ("author", "is_bot", "channel"),
    [(999, False, CHANNEL), (OWNER, True, CHANNEL), (OWNER, False, 1)],
)
def test_strangers_get_no_reply_and_write_nothing(
    config: Config, author: int, is_bot: bool, channel: int
) -> None:
    for content in ("!addtopic Heap", "!topics"):
        assert handle_message(content, author, is_bot, channel, config, NOW) is None
    assert not config.data_dir.exists()


def test_commands_are_case_insensitive(config: Config) -> None:
    assert "Heap" in send(config, "!ADDTOPIC Heap").text
    assert "Heap" in send(config, "!Topics").text


def test_mentions_are_escaped_in_confirmation_and_listing_but_not_in_file(config: Config) -> None:
    for raw in ("@everyone", "<@123>"):
        confirm = send(config, f"!addtopic {raw}").text
        assert raw not in confirm
    listing = send(config, "!topics").text
    assert "@everyone" not in listing and "<@123>" not in listing
    stored = json.loads(custom_path(config).read_text("utf-8"))["topics"]
    assert stored == ["@everyone", "<@123>"]


# !study replies point to !topics (criterion 45)


def test_study_without_topic_asks_which_topic_and_mentions_topics(config: Config) -> None:
    text = send(config, "!study").text
    assert "Which topic" in text and "!topics" in text and "Hashing" in text
    assert "don't know" not in text


def test_unknown_and_ambiguous_replies_mention_topics(config: Config) -> None:
    assert "!topics" in send(config, "!study zzz").text
    ambiguous = send(config, "!study linked").text
    assert "!topics" in ambiguous and "Linked List II" in ambiguous
    assert not (config.data_dir / "current_session.json").exists()
