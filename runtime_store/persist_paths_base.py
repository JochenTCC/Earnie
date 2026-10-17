"""Env root, config/runtime directories and runtime state file paths (split from persist_paths)."""
from __future__ import annotations

import os
from runtime_store.env_vars import read_env, read_runtime_path


_DEFAULT_ENV_ROOT = "earnie_env"


_LEGACY_CONFIG_DIR = "config"


_LEGACY_RUNTIME_DIR = "runtime"


_LEGACY_DOTENV_IN_CONFIG = os.path.join(_LEGACY_CONFIG_DIR, ".env")


_LEGACY_DOTENV = ".env"


def env_root() -> str:
    """Env-Wurzel: cloud session override, else EARNIE_ENV_PATH (Default: earnie_env)."""
    from runtime_store.cloud_demo import get_session_env_root

    session = get_session_env_root()
    if session:
        return session
    env = read_env("ENV_PATH")
    return env if env else _DEFAULT_ENV_ROOT


def _preferred_config_dir() -> str:
    return os.path.join(env_root(), "config")


def _preferred_runtime_dir() -> str:
    return os.path.join(env_root(), "runtime")


def _preferred_dotenv() -> str:
    return os.path.join(_preferred_config_dir(), ".env")


def _env_path_explicit() -> bool:
    """True when EARNIE_ENV_PATH is set in the process env."""
    raw = os.environ.get("EARNIE_ENV_PATH")
    if raw is not None and str(raw).strip():
        return True
    return False


def _path_is_under(path: str, root: str) -> bool:
    try:
        abs_path = os.path.abspath(path)
        abs_root = os.path.abspath(root)
        return os.path.commonpath([abs_path, abs_root]) == abs_root
    except (ValueError, OSError):
        return False


def _effective_config_path_env() -> str:
    """
    CONFIG_PATH from env, ignored when an explicit ENV_PATH scopes the tree
    and CONFIG_PATH points outside that root (e.g. leftover NAS redirect in
    legacy config/.env while launch sets EARNIE_ENV_PATH=earnie_env).

    Exception: Home Assistant add-on keeps config on Supervisor ``addon_config``
    (``EARNIE_CONFIG_PATH=/config``) and runtime under ``EARNIE_ENV_PATH`` —
    that split is intentional; do not drop ``/config``.
    """
    env = read_env("CONFIG_PATH")
    if not env:
        return ""
    if not _env_path_explicit():
        return env
    if read_env("INSTALL_CONTEXT").strip().lower() == "homeassistant_addon":
        return env
    root = env_root()
    cfg_dir = _config_dir_from_config_path_env(env)
    if _path_is_under(cfg_dir, root):
        return env
    return ""


def _is_legacy_config_file_path(raw: str) -> bool:
    """True if CONFIG_PATH still points at a *.json file (pre-directory semantics)."""
    base = os.path.basename(raw.replace("\\", "/"))
    return base.endswith(".json")


def _config_dir_from_config_path_env(raw: str) -> str:
    """Interpret CONFIG_PATH as config directory; accept legacy …/config.json."""
    if _is_legacy_config_file_path(raw):
        parent = os.path.dirname(raw)
        return parent if parent else "."
    return raw


def default_config_dir() -> str:
    """Aktives Config-Verzeichnis ohne CONFIG_PATH (ENV_PATH/config, sonst legacy)."""
    preferred = _preferred_config_dir()
    if os.path.isdir(preferred):
        return preferred
    if env_root() == _DEFAULT_ENV_ROOT and os.path.isdir(_LEGACY_CONFIG_DIR):
        return _LEGACY_CONFIG_DIR
    return preferred


def config_dir() -> str:
    """Config-Verzeichnis: cloud session, else CONFIG_PATH-ENV oder default_config_dir()."""
    from runtime_store.cloud_demo import get_session_env_root

    session = get_session_env_root()
    if session:
        return os.path.join(session, "config")
    env_dir = _config_directory_from_env()
    if env_dir:
        return env_dir
    return default_config_dir()


def config_path(*parts: str) -> str:
    return os.path.join(config_dir(), *parts)


def _preferred_or_legacy_file(*relative_parts: str) -> str:
    """Datei unter ENV_PATH/config, sonst legacy config/, sonst preferred Pfad."""
    preferred = os.path.join(_preferred_config_dir(), *relative_parts)
    if os.path.isfile(preferred):
        return preferred
    legacy = os.path.join(_LEGACY_CONFIG_DIR, *relative_parts)
    if os.path.isfile(legacy):
        return legacy
    return preferred


def runtime_dir() -> str:
    from runtime_store.cloud_demo import get_session_env_root

    session = get_session_env_root()
    if session:
        return os.path.join(session, "runtime")
    env = read_runtime_path()
    if env:
        return env
    preferred = _preferred_runtime_dir()
    if os.path.isdir(preferred):
        return preferred
    if env_root() == _DEFAULT_ENV_ROOT and os.path.isdir(_LEGACY_RUNTIME_DIR):
        return _LEGACY_RUNTIME_DIR
    return preferred


def runtime_path(filename: str) -> str:
    return os.path.join(runtime_dir(), filename)


def resolve_backtesting_log_dir() -> str:
    """Zielordner für backtesting_log.json und backtesting.csv (UI und Laufzeit)."""
    return runtime_dir()


def resolve_runtime_prefixed_path(configured_path: str) -> str:
    """
    Relative Pfade mit ``runtime/``-Präfix gegen ``runtime_dir()`` auflösen.

    So greift ``EARNIE_RUNTIME_PATH`` auch für ``path_cons_data`` in
    config.json (z. B. Dev mit NAS-Config, Docker unverändert).
    """
    if os.path.isabs(configured_path):
        return configured_path
    norm = configured_path.replace("\\", "/")
    if norm.startswith("runtime/"):
        return runtime_path(norm[len("runtime/") :])
    env_runtime_prefix = env_root().replace("\\", "/") + "/runtime/"
    if norm.startswith(env_runtime_prefix):
        return runtime_path(norm[len(env_runtime_prefix) :])
    if norm.startswith("earnie_env/runtime/"):
        return runtime_path(norm[len("earnie_env/runtime/") :])
    return configured_path


def resolve_config_prefixed_path(configured_path: str) -> str:
    """
    Relative Pfade mit ``config/``-Präfix gegen ``config_dir()`` auflösen.

    Deckt auch ``{ENV_PATH}/config/…`` und hält gespeicherte ``config/uploads/…``-Pfade portabel.
    """
    if os.path.isabs(configured_path):
        return configured_path
    norm = configured_path.replace("\\", "/")
    env_config_prefix = env_root().replace("\\", "/") + "/config/"
    if norm.startswith(env_config_prefix):
        return config_path(norm[len(env_config_prefix) :])
    if norm.startswith("earnie_env/config/"):
        return config_path(norm[len("earnie_env/config/") :])
    if norm.startswith("config/"):
        return config_path(norm[len("config/") :])
    return configured_path


def resolve_uploads_dir() -> str:
    """Upload-Verzeichnis neben der aktiven config.json."""
    return config_path("uploads")


def consumer_state_file() -> str:
    return runtime_path("flexible_consumers_state.json")


def usage_ping_state_file() -> str:
    return runtime_path("usage_ping.json")


def pv_counter_state_file() -> str:
    return runtime_path("pv_counter_state.json")


def power_interval_sampler_state_file() -> str:
    return runtime_path("power_interval_sampler_state.json")


def cons_data_pending_file() -> str:
    return runtime_path("cons_data_pending.json")


def log_file() -> str:
    """Absolute path so FileHandler does not depend on process cwd."""
    return os.path.abspath(runtime_path("earnie.log"))


def daemon_stdio_log_file() -> str:
    """Stdout/stderr capture for UI-/auto-started ``main.py`` (not earnie.log)."""
    return os.path.abspath(runtime_path("main_stdio.log"))


def consumption_profiles_file() -> str:
    return runtime_path("consumption_profiles.csv")


def total_consumption_profiles_file() -> str:
    return runtime_path("total_consumption_profiles.csv")


def flexible_consumer_profiles_file() -> str:
    return runtime_path("flexible_consumer_profiles.csv")


def _config_directory_from_env() -> str | None:
    """Config-Verzeichnis aus CONFIG_PATH-ENV, sonst None."""
    env = _effective_config_path_env()
    if not env:
        return None
    return _config_dir_from_config_path_env(env)
