import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ModulesError(Exception):
    """modules.json is unusable as a whole. The message is one short line."""


@dataclass(frozen=True)
class Module:
    name: str
    folder: str | None
    total_coding_problems: int | None
    solved_before_repo: int


def normalize_name(text: str) -> str:
    return text.lower().replace(" ", "").replace("-", "").replace("_", "")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _read_entries(path: Path) -> list[Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError:
        raise ModulesError(f"cannot read {path}") from None
    except ValueError:  # JSONDecodeError and UnicodeDecodeError
        raise ModulesError(f"{path} is not valid JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("modules"), list):
        raise ModulesError(f"{path} must be an object with a 'modules' list")
    if not data["modules"]:
        raise ModulesError(f"{path} has an empty 'modules' list")
    return data["modules"]


def _folder(label: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ModulesError(f"{label}: folder must be a string or null")
    # The folder is joined to HUB_PATH later, so it must be one plain path component.
    if not value.strip() or value in (".", "..") or any(c in value for c in "/\\:"):
        raise ModulesError(f"{label}: folder must be a single folder name")
    return value


def _parse_entry(index: int, entry: Any) -> Module:
    if not isinstance(entry, dict):
        raise ModulesError(f"entry {index} is not an object")
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ModulesError(f"entry {index}: name must be a non-empty string")
    label = f"module {name!r}"
    if not normalize_name(name):
        raise ModulesError(f"entry {index}: {label} has only spaces, hyphens or underscores")
    total = entry.get("total_coding_problems")
    if total is not None and not (_is_int(total) and total > 0):
        raise ModulesError(f"{label}: total_coding_problems must be a positive integer or null")
    solved = entry.get("solved_before_repo", 0)
    if not (_is_int(solved) and solved >= 0):
        raise ModulesError(f"{label}: solved_before_repo must be a non-negative integer")
    return Module(name, _folder(label, entry.get("folder")), total, solved)


def load_modules(path: Path) -> tuple[Module, ...]:
    modules = tuple(_parse_entry(i, entry) for i, entry in enumerate(_read_entries(path), 1))
    seen: dict[str, str] = {}
    for module in modules:
        key = normalize_name(module.name)
        if key in seen:
            raise ModulesError(f"modules {seen[key]!r} and {module.name!r} have the same name")
        seen[key] = module.name
    return modules
