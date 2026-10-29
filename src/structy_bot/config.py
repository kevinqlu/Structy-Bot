import math
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_HUB_PATH = r"C:\Users\kevin\code\Structy-Hub"
DEFAULT_SYNC_SCRIPT = DEFAULT_HUB_PATH + r"\_tools\sync_progress.ps1"
REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(Exception):
    """Invalid configuration. The message names the variable, never its value."""


@dataclass(frozen=True)
class Config:
    discord_token: str = field(repr=False)
    owner_id: int
    channel_id: int
    sync_script_path: Path
    sync_log_path: Path
    hub_path: Path
    modules_path: Path
    data_dir: Path
    sync_timeout_seconds: float
    max_session_hours: float


def _get(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name, "").strip()
    return value or None


def _required(environ: Mapping[str, str], name: str) -> str:
    value = _get(environ, name)
    if value is None:
        raise ConfigError(f"{name} is missing or blank")
    return value


def _integer(environ: Mapping[str, str], name: str) -> int:
    try:
        return int(_required(environ, name))
    except ValueError:
        raise ConfigError(f"{name} must be an integer") from None


def _positive_number(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = _get(environ, name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a positive number") from None
    if not math.isfinite(value) or value <= 0:
        raise ConfigError(f"{name} must be a positive number")
    return value


def _sync_log_path(environ: Mapping[str, str]) -> Path:
    explicit = _get(environ, "SYNC_LOG_PATH")
    if explicit:
        return Path(explicit)
    local_app_data = _get(environ, "LOCALAPPDATA")
    if local_app_data is None:
        raise ConfigError("SYNC_LOG_PATH is not set and LOCALAPPDATA is unavailable")
    return Path(local_app_data) / "structy-sync.log"


def load_config(environ: Mapping[str, str]) -> Config:
    hub_path = Path(_get(environ, "HUB_PATH") or DEFAULT_HUB_PATH)
    modules_path = _get(environ, "MODULES_PATH")
    data_dir = _get(environ, "DATA_DIR")
    return Config(
        discord_token=_required(environ, "DISCORD_TOKEN"),
        owner_id=_integer(environ, "OWNER_ID"),
        channel_id=_integer(environ, "CHANNEL_ID"),
        sync_script_path=Path(_get(environ, "SYNC_SCRIPT_PATH") or DEFAULT_SYNC_SCRIPT),
        sync_log_path=_sync_log_path(environ),
        hub_path=hub_path,
        modules_path=Path(modules_path) if modules_path else hub_path / "modules.json",
        data_dir=Path(data_dir) if data_dir else REPO_ROOT / "data",
        sync_timeout_seconds=_positive_number(environ, "SYNC_TIMEOUT_SECONDS", 120),
        max_session_hours=_positive_number(environ, "MAX_SESSION_HOURS", 6),
    )


def load_or_exit() -> Config:
    load_dotenv(REPO_ROOT / ".env")
    try:
        return load_config(os.environ)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
