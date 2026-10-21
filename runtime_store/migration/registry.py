"""Ordered MigrationStep registry (ConfigMigration P1)."""
from __future__ import annotations

from runtime_store.migration.steps.consumer_flex_bindings import (
    STEP as CONSUMER_FLEX,
)
from runtime_store.migration.steps.conversion_efficiency import STEP as CONVERSION
from runtime_store.migration.steps.ehal_bindings import STEP as EHAL
from runtime_store.migration.steps.ess_bindings import STEP as ESS
from runtime_store.migration.steps.grid_fee_profile import STEP as GRID_FEE
from runtime_store.migration.steps.inverters import STEP as INVERTERS
from runtime_store.migration.steps.loxone_binding_names import STEP as LOXONE_NAMES
from runtime_store.migration.steps.pool_filter import STEP as POOL_FILTER
from runtime_store.migration.steps.ehal_http_port import STEP as EHAL_HTTP_PORT
from runtime_store.migration.steps.ha_pull_removal import STEP as HA_PULL_REMOVAL
from runtime_store.migration.steps.required_signal_activation import (
    STEP as REQUIRED_SIGNALS,
)
from runtime_store.migration.steps.retire_plant_pv_binding import (
    STEP as RETIRE_PLANT_PV,
)
from runtime_store.migration.steps.se_conf_defaults import STEP as SE_CONF_DEFAULTS
from runtime_store.migration.steps.topology import STEP as TOPOLOGY
from runtime_store.migration.steps.v3_to_v4 import STEP as V3_TO_V4
from runtime_store.migration.types import MigrationStep

# Inventory order (Earnie-env-home chronology + code dependencies)
STEPS: tuple[MigrationStep, ...] = (
    EHAL,
    V3_TO_V4,
    ESS,
    LOXONE_NAMES,
    INVERTERS,
    CONVERSION,
    TOPOLOGY,
    POOL_FILTER,
    GRID_FEE,
    REQUIRED_SIGNALS,
    HA_PULL_REMOVAL,
    EHAL_HTTP_PORT,
    CONSUMER_FLEX,
    RETIRE_PLANT_PV,
    SE_CONF_DEFAULTS,
)

STEP_BY_ID: dict[str, MigrationStep] = {step.id: step for step in STEPS}
