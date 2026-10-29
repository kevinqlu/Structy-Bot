import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from structy_bot.modules import Module, normalize_name

FREE_TEXT_MAX_CHARS = 40


class TopicKind(Enum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"
    EMPTY = "empty"


@dataclass(frozen=True)
class TopicMatch:
    kind: TopicKind
    module: Module | None = None
    candidates: tuple[Module, ...] = ()


def resolve_topic(text: str, modules: Sequence[Module]) -> TopicMatch:
    key = normalize_name(text.strip())  # strip so tab/newline-only input counts as empty
    if not key:
        return TopicMatch(TopicKind.EMPTY)
    # Exact match first, so "binary tree i" is not ambiguous with "Binary Tree II".
    for module in modules:
        if normalize_name(module.name) == key:
            return TopicMatch(TopicKind.MATCHED, module)
    prefixed = tuple(m for m in modules if normalize_name(m.name).startswith(key))
    if len(prefixed) == 1:
        return TopicMatch(TopicKind.MATCHED, prefixed[0])
    if prefixed:
        return TopicMatch(TopicKind.AMBIGUOUS, candidates=prefixed)
    return TopicMatch(TopicKind.UNKNOWN)


def clean_free_text_topic(text: str) -> str | None:
    """Fallback-mode topic. Mentions are NOT escaped here; that happens at display time."""
    # Cc (e.g. NUL, ESC) and Cf (zero-width, bidi overrides) are dropped; whitespace
    # controls such as tab and newline are turned into spaces first so words stay apart.
    spaced = "".join(" " if c.isspace() else c for c in text)
    kept = "".join(c for c in spaced if unicodedata.category(c) not in ("Cc", "Cf"))
    collapsed = " ".join(kept.split())
    return collapsed[:FREE_TEXT_MAX_CHARS].rstrip() or None
