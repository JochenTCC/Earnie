"""
persist_paths.py – Pfade für persistente Laufzeitdateien (unter earnie_env/).
"""
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
    """True when EARNIE_ENV_PATH / ENERGY_OPTIMIZER_ENV_PATH is set in the process env."""
    for key in ("EARNIE_ENV_PATH", "ENERGY_OPTIMIZER_ENV_PATH"):
        raw = os.environ.get(key)
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
    """
    env = read_env("CONFIG_PATH")
    if not env:
        return ""
    if not _env_path_explicit():
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
    """Zielordner für backtesting_log.json und backtesting_hourly.csv (UI und Laufzeit)."""
    return runtime_dir()


def resolve_runtime_prefixed_path(configured_path: str) -> str:
    """
    Relative Pfade mit ``runtime/``-Präfix gegen ``runtime_dir()`` auflösen.

    So greift ``EARNIE_RUNTIME_PATH`` (bzw. Legacy ``ENERGY_OPTIMIZER_RUNTIME_PATH`` / ``*_RUNTIME_DIR``) auch für ``path_cons_data`` in
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


def pv_counter_state_file() -> str:
    return runtime_path("pv_counter_state.json")


def cons_data_pending_file() -> str:
    return runtime_path("cons_data_pending.json")


def log_file() -> str:
    return runtime_path("earnie.log")


def consumption_profiles_file() -> str:
    return runtime_path("consumption_profiles.csv")


def total_consumption_profiles_file() -> str:
    return runtime_path("total_consumption_profiles.csv")


def flexible_consumer_profiles_file() -> str:
    return runtime_path("flexible_consumer_profiles.csv")


def legacy_history_csv_file() -> str:
    return runtime_path("system_history_log.csv")


def default_cons_data_file() -> str:
    return runtime_path("cons_data_hourly.csv")


def bundled_config_dir() -> str:
    """Im Image gebündelte Config-Vorlagen (nicht vom NAS-Volume überschrieben)."""
    return os.path.join("share", "config")


def bundled_config_example_file() -> str:
    return os.path.join(bundled_config_dir(), "config.example.json")


def bundled_config_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "config.minimal.json")


def bundled_config_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "config.schema.json")


def resolve_config_template_path() -> str:
    """Vorlage für config.example.json: Mount, Legacy oder gebündelte Image-Kopie."""
    preferred = _preferred_or_legacy_file("config.example.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "config.example.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_config_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_config_minimal_template_path() -> str:
    """Vorlage für neue config.json (Greenfield-Bootstrap, ohne Hausdaten)."""
    preferred = _preferred_or_legacy_file("config.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_config_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def config_example_file() -> str:
    """Pfad zur Config-Vorlage im Persistenz-Ordner (für Drift-Vergleich)."""
    preferred = _preferred_or_legacy_file("config.example.json")
    legacy = "config.example.json"
    if os.path.isfile(preferred):
        return preferred
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_config_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def config_schema_file() -> str:
    """Pfad zum JSON-Schema im Persistenz-Ordner."""
    preferred = _preferred_or_legacy_file("config.schema.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "config.schema.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_config_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_config_schema_template_path() -> str:
    """Schema-Vorlage: Mount, Legacy oder gebündelte Image-Kopie."""
    return config_schema_file()


def resolve_config_json_path() -> str:
    """Pfad zu config.json: cloud session > CONFIG_PATH-Dir > ENV_PATH/config > legacy."""
    from runtime_store.cloud_demo import get_session_env_root

    session = get_session_env_root()
    if session:
        return os.path.join(session, "config", "config.json")
    env = _effective_config_path_env()
    if env:
        if _is_legacy_config_file_path(env):
            return env
        return os.path.join(env, "config.json")
    preferred = os.path.join(_preferred_config_dir(), "config.json")
    if os.path.isfile(preferred):
        return preferred
    legacy_dir = os.path.join(_LEGACY_CONFIG_DIR, "config.json")
    if os.path.isfile(legacy_dir):
        return legacy_dir
    legacy = "config.json"
    if os.path.isfile(legacy):
        return legacy
    return preferred


def _config_directory_from_env() -> str | None:
    """Config-Verzeichnis aus CONFIG_PATH-ENV, sonst None."""
    env = _effective_config_path_env()
    if not env:
        return None
    return _config_dir_from_config_path_env(env)


def _resolve_sidecar_json_path(
    *,
    env_suffix: str,
    filename: str,
    default_path: str,
    legacy_basename: str | None = None,
) -> str:
    """
    Sidecar-JSON im Config-Verzeichnis, wenn CONFIG_PATH per ENV gesetzt ist.

    Reihenfolge: cloud session > explizite Sidecar-ENV > vorhandene Datei im Config-Dir >
    vorhandener Default/Legacy > (bei CONFIG_PATH) Zielpfad im Config-Dir >
    Default-Pfad.
    """
    from runtime_store.cloud_demo import get_session_env_root

    if get_session_env_root():
        return os.path.join(config_dir(), filename)
    env = read_env(env_suffix)
    if env:
        return env
    config_directory = _config_directory_from_env()
    if config_directory:
        co_located = os.path.join(config_directory, filename)
        if os.path.isfile(co_located):
            return co_located
    if os.path.isfile(default_path):
        return default_path
    legacy_in_config = os.path.join(_LEGACY_CONFIG_DIR, filename)
    if os.path.isfile(legacy_in_config):
        return legacy_in_config
    if legacy_basename and os.path.isfile(legacy_basename):
        return legacy_basename
    if config_directory:
        return os.path.join(config_directory, filename)
    return default_path


def local_settings_file() -> str:
    return runtime_path("local_settings.json")


def local_settings_example_file() -> str:
    return runtime_path("local_settings.example.json")


def resolve_local_settings_template_path() -> str:
    """Vorlage für local_settings.json: Runtime-Mount oder gebündelte Image-Kopie."""
    preferred = local_settings_example_file()
    if os.path.isfile(preferred):
        return preferred
    legacy = os.path.join(_LEGACY_RUNTIME_DIR, "local_settings.example.json")
    if os.path.isfile(legacy):
        return legacy
    bundled = os.path.join(bundled_config_dir(), "local_settings.example.json")
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_local_settings_json_path() -> str:
    """Maschinenspezifische Einstellungen: cloud session / runtime > ENV > runtime/local_settings.json."""
    from runtime_store.cloud_demo import get_session_env_root

    if get_session_env_root():
        return local_settings_file()
    env = read_env("LOCAL_SETTINGS_PATH")
    if env:
        return env
    return local_settings_file()


def bundled_backtesting_scenarios_example_file() -> str:
    return os.path.join(bundled_config_dir(), "backtesting_scenarios.example.json")


def bundled_backtesting_scenarios_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "backtesting_scenarios.minimal.json")


def bundled_backtesting_scenarios_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "backtesting_scenarios.schema.json")


def resolve_backtesting_scenarios_template_path() -> str:
    """Vorlage für backtesting_scenarios.example.json: Mount, Legacy oder gebündelte Image-Kopie."""
    preferred = _preferred_or_legacy_file("backtesting_scenarios.example.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "backtesting_scenarios.example.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_backtesting_scenarios_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_backtesting_scenarios_minimal_template_path() -> str:
    """Vorlage für neue backtesting_scenarios.json (leere Szenarien)."""
    preferred = _preferred_or_legacy_file("backtesting_scenarios.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_backtesting_scenarios_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_backtesting_scenarios_schema_template_path() -> str:
    """Schema-Vorlage für backtesting_scenarios.json."""
    preferred = _preferred_or_legacy_file("backtesting_scenarios.schema.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "backtesting_scenarios.schema.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_backtesting_scenarios_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_backtesting_scenarios_json_path() -> str:
    """Pfad zu backtesting_scenarios.json: ENV > neben config.json > earnie_env/config > Legacy."""
    return _resolve_sidecar_json_path(
        env_suffix="BACKTESTING_SCENARIOS_PATH",
        filename="backtesting_scenarios.json",
        default_path=os.path.join(_preferred_config_dir(), "backtesting_scenarios.json"),
        legacy_basename="backtesting_scenarios.json",
    )


def bundled_tariffs_example_file() -> str:
    return os.path.join(bundled_config_dir(), "tariffs.example.json")


def bundled_tariffs_catalog_file() -> str:
    """Published full tariff catalog under share/config/tariffs.json."""
    return os.path.join(bundled_config_dir(), "tariffs.json")


def bundled_tariffs_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "tariffs.minimal.json")


def bundled_tariffs_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "tariffs.schema.json")


def resolve_tariffs_template_path() -> str:
    preferred = _preferred_or_legacy_file("tariffs.example.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_tariffs_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_tariffs_catalog_template_path() -> str:
    """Full public catalog for seeding site tariffs.json (prefer share/config)."""
    preferred = _preferred_or_legacy_file("tariffs.json")
    # Preferred path is the live site file — only use it as a *template* if we are
    # not about to bootstrap that same path. Callers should prefer bundled catalog.
    bundled = bundled_tariffs_catalog_file()
    if os.path.isfile(bundled):
        return bundled
    if os.path.isfile(preferred):
        return preferred
    return bundled


def resolve_tariffs_minimal_template_path() -> str:
    """Vorlage für neue tariffs.json (leere Tarif-Kataloge)."""
    preferred = _preferred_or_legacy_file("tariffs.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_tariffs_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_tariffs_schema_template_path() -> str:
    preferred = _preferred_or_legacy_file("tariffs.schema.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_tariffs_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_tariffs_json_path() -> str:
    """Pfad zu tariffs.json: ENV > neben config.json > earnie_env/config."""
    return _resolve_sidecar_json_path(
        env_suffix="TARIFFS_PATH",
        filename="tariffs.json",
        default_path=os.path.join(_preferred_config_dir(), "tariffs.json"),
    )


def bundled_house_profiles_example_file() -> str:
    return os.path.join(bundled_config_dir(), "house_profiles.example.json")


def bundled_house_profiles_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "house_profiles.minimal.json")


def bundled_house_profiles_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "house_profiles.schema.json")


def resolve_house_profiles_template_path() -> str:
    preferred = _preferred_or_legacy_file("house_profiles.example.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_house_profiles_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_house_profiles_minimal_template_path() -> str:
    """Vorlage für neue house_profiles.json (leere Profile)."""
    preferred = _preferred_or_legacy_file("house_profiles.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_house_profiles_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_house_profiles_schema_template_path() -> str:
    preferred = _preferred_or_legacy_file("house_profiles.schema.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_house_profiles_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_house_profiles_json_path() -> str:
    """Pfad zu house_profiles.json: ENV > neben config.json > earnie_env/config."""
    return _resolve_sidecar_json_path(
        env_suffix="HOUSE_PROFILES_PATH",
        filename="house_profiles.json",
        default_path=os.path.join(_preferred_config_dir(), "house_profiles.json"),
    )


def bundled_components_example_file() -> str:
    return os.path.join(bundled_config_dir(), "components.example.json")


def bundled_components_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "components.minimal.json")


def bundled_components_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "components.schema.json")


def resolve_components_template_path() -> str:
    preferred = _preferred_or_legacy_file("components.example.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_components_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_components_minimal_template_path() -> str:
    """Vorlage für neue components.json (leere Kataloge)."""
    preferred = _preferred_or_legacy_file("components.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_components_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_components_schema_template_path() -> str:
    preferred = _preferred_or_legacy_file("components.schema.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_components_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_components_json_path() -> str:
    """Pfad zu components.json: ENV > neben config.json > earnie_env/config."""
    return _resolve_sidecar_json_path(
        env_suffix="COMPONENTS_PATH",
        filename="components.json",
        default_path=os.path.join(_preferred_config_dir(), "components.json"),
    )


def bundled_deviation_rules_example_file() -> str:
    return os.path.join(bundled_config_dir(), "deviation_rules.example.json")


def bundled_deviation_rules_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "deviation_rules.schema.json")


def resolve_deviation_rules_template_path() -> str:
    """Vorlage für deviation_rules.json: Mount, Legacy oder gebündelte Image-Kopie."""
    preferred = _preferred_or_legacy_file("deviation_rules.example.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "deviation_rules.example.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_deviation_rules_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_deviation_rules_schema_template_path() -> str:
    """Schema-Vorlage für deviation_rules.json."""
    preferred = _preferred_or_legacy_file("deviation_rules.schema.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "deviation_rules.schema.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_deviation_rules_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_deviation_rules_json_path() -> str:
    """Pfad zu deviation_rules.json: ENV > neben config.json > earnie_env/config > Legacy > Vorlage."""
    return _resolve_sidecar_json_path(
        env_suffix="DEVIATION_RULES_PATH",
        filename="deviation_rules.json",
        default_path=os.path.join(_preferred_config_dir(), "deviation_rules.json"),
        legacy_basename="deviation_rules.json",
    )


def bundled_dotenv_example_file() -> str:
    return os.path.join(bundled_config_dir(), ".env.example")


def resolve_dotenv_path() -> str:
    """Pfad zur .env: cloud session > ENV > Config-Dir > ENV_PATH/config/.env > legacy."""
    from runtime_store.cloud_demo import get_session_env_root

    if get_session_env_root():
        return os.path.join(config_dir(), ".env")
    env = read_env("DOTENV_PATH")
    if env:
        return env
    preferred_dotenv = _preferred_dotenv()
    # Explicit ENV_PATH (launch.json / greenfield): stay inside that tree.
    # Do not fall back to legacy config/.env (often still points at NAS).
    if _env_path_explicit():
        if os.path.isfile(preferred_dotenv):
            return preferred_dotenv
        if os.path.isfile(_LEGACY_DOTENV):
            return _LEGACY_DOTENV
        return preferred_dotenv
    config_directory = _config_directory_from_env()
    if config_directory:
        co_located = os.path.join(config_directory, ".env")
        if os.path.isfile(co_located):
            return co_located
        # Prefer co-located path for new bootstraps when CONFIG_PATH is set.
        if not os.path.isfile(preferred_dotenv) and not os.path.isfile(
            _LEGACY_DOTENV_IN_CONFIG
        ):
            return co_located
    if os.path.isfile(preferred_dotenv):
        return preferred_dotenv
    # Prefer repo-root .env over legacy config/.env when preferred is missing.
    if os.path.isfile(_LEGACY_DOTENV):
        return _LEGACY_DOTENV
    if os.path.isfile(_LEGACY_DOTENV_IN_CONFIG):
        return _LEGACY_DOTENV_IN_CONFIG
    if config_directory:
        return os.path.join(config_directory, ".env")
    return preferred_dotenv


def resolve_dotenv_template_path() -> str:
    """Vorlage für .env: Repo-.env.example oder gebündelte Image-Kopie."""
    if os.path.isfile(".env.example"):
        return ".env.example"
    bundled = bundled_dotenv_example_file()
    if os.path.isfile(bundled):
        return bundled
    return bundled
