from pathlib import Path

import pytest

from structy_bot import config as config_module
from structy_bot.config import Config, ConfigError, load_config, load_or_exit

TOKEN = "super-secret-token-value"
MINIMAL = {
    "DISCORD_TOKEN": TOKEN,
    "OWNER_ID": "111",
    "CHANNEL_ID": "222",
    "LOCALAPPDATA": r"C:\Users\kevin\AppData\Local",
}


def env(**overrides: str) -> dict[str, str]:
    return {**MINIMAL, **overrides}


def test_minimal_env_applies_spec_defaults() -> None:
    cfg = load_config(MINIMAL)
    repo_root = Path(config_module.__file__).resolve().parents[2]
    assert cfg.discord_token == TOKEN
    assert cfg.owner_id == 111
    assert cfg.channel_id == 222
    assert cfg.sync_script_path == Path(r"C:\Users\kevin\code\Structy-Hub\_tools\sync_progress.ps1")
    assert cfg.hub_path == Path(r"C:\Users\kevin\code\Structy-Hub")
    assert cfg.modules_path == cfg.hub_path / "modules.json"
    assert cfg.sync_log_path == Path(r"C:\Users\kevin\AppData\Local") / "structy-sync.log"
    assert cfg.data_dir == repo_root / "data"
    assert cfg.sync_timeout_seconds == 120
    assert cfg.max_session_hours == 6


def test_config_is_frozen() -> None:
    cfg = load_config(MINIMAL)
    with pytest.raises(AttributeError):
        cfg.owner_id = 5  # type: ignore[misc]


@pytest.mark.parametrize("name", ["DISCORD_TOKEN", "OWNER_ID", "CHANNEL_ID"])
def test_missing_required_variable_is_named(name: str) -> None:
    environ = {k: v for k, v in MINIMAL.items() if k != name}
    with pytest.raises(ConfigError, match=name):
        load_config(environ)


@pytest.mark.parametrize("name", ["DISCORD_TOKEN", "OWNER_ID", "CHANNEL_ID"])
@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_required_variable_counts_as_missing(name: str, blank: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_config(env(**{name: blank}))


@pytest.mark.parametrize("name", ["OWNER_ID", "CHANNEL_ID"])
def test_non_integer_id_is_named(name: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_config(env(**{name: "12ab"}))


def test_modules_path_follows_overridden_hub_path() -> None:
    cfg = load_config(env(HUB_PATH=r"D:\hub"))
    assert cfg.modules_path == Path(r"D:\hub") / "modules.json"


def test_overrides_are_applied() -> None:
    cfg = load_config(
        env(
            SYNC_SCRIPT_PATH=r"D:\s.ps1",
            SYNC_LOG_PATH=r"D:\s.log",
            MODULES_PATH=r"D:\m.json",
            DATA_DIR=r"D:\data",
            SYNC_TIMEOUT_SECONDS="30",
            MAX_SESSION_HOURS="2.5",
        )
    )
    assert cfg.sync_script_path == Path(r"D:\s.ps1")
    assert cfg.sync_log_path == Path(r"D:\s.log")
    assert cfg.modules_path == Path(r"D:\m.json")
    assert cfg.data_dir == Path(r"D:\data")
    assert cfg.sync_timeout_seconds == 30
    assert cfg.max_session_hours == 2.5


def test_missing_localappdata_without_log_path_names_sync_log_path() -> None:
    environ = {k: v for k, v in MINIMAL.items() if k != "LOCALAPPDATA"}
    with pytest.raises(ConfigError, match="SYNC_LOG_PATH"):
        load_config(environ)
    assert load_config({**environ, "SYNC_LOG_PATH": r"D:\s.log"}).sync_log_path == Path(r"D:\s.log")


@pytest.mark.parametrize("name", ["SYNC_TIMEOUT_SECONDS", "MAX_SESSION_HOURS"])
@pytest.mark.parametrize("bad", ["0", "-5", "abc", "nan", "inf"])
def test_non_positive_or_invalid_number_is_named(name: str, bad: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_config(env(**{name: bad}))


def test_token_never_leaks_in_errors_or_repr() -> None:
    assert TOKEN not in repr(load_config(MINIMAL))
    for bad in (env(OWNER_ID="x"), env(CHANNEL_ID=""), env(SYNC_TIMEOUT_SECONDS="0")):
        with pytest.raises(ConfigError) as excinfo:
            load_config(bad)
        assert TOKEN not in str(excinfo.value)


def test_load_or_exit_returns_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_module, "load_dotenv", lambda path: False)
    for key, value in MINIMAL.items():
        monkeypatch.setenv(key, value)
    assert isinstance(load_or_exit(), Config)


def test_load_or_exit_exits_1_naming_variable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(config_module, "load_dotenv", lambda path: False)
    for key, value in MINIMAL.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("OWNER_ID")
    with pytest.raises(SystemExit) as excinfo:
        load_or_exit()
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "Configuration error: OWNER_ID is missing or blank"
    assert TOKEN not in captured.err + captured.out


def test_load_or_exit_loads_dotenv_from_the_repo_not_the_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []
    monkeypatch.setattr(config_module, "load_dotenv", lambda path: seen.append(path) or False)
    for key, value in MINIMAL.items():
        monkeypatch.setenv(key, value)
    load_or_exit()
    assert seen == [config_module.REPO_ROOT / ".env"]
