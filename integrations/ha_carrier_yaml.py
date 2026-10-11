"""Minimal Home Assistant Weg B carrier YAML (rest_command push + status.json poll)."""
from __future__ import annotations

from ehal.push_signals import (
    heartbeat_signal,
    read_signals_from_docs,
)
from scripts.pilot_vo_template_gen import TOKEN_PLACEHOLDER


def build_carrier_yaml(
    house: dict,
    components: dict,
    *,
    earnie_host: str,
    earnie_port: int,
    token: str = TOKEN_PLACEHOLDER,
) -> str:
    """Return a YAML fragment (rest_command push + REST sensor for status.json)."""
    base = f"http://{earnie_host}:{earnie_port}"
    token_q = f"?t={token}"
    lines: list[str] = [
        "# Earnie Weg B carrier fragment (2.7.r-T4) — merge into configuration.yaml",
        "# Push path values must already be in canonical EHAL units (W, kWh, %, A).",
        "# Replace ENTITY_* placeholders with mapped HA entity_ids from EHAL-Com.",
        "rest_command:",
    ]
    for sig in read_signals_from_docs(house, components):
        cmd_name = sig.title.replace("Push_", "earnie_push_").lower()
        if sig.digital:
            on_url = f"{base}/ehal/telemetry/{sig.ehal_id}/1{token_q}"
            off_url = f"{base}/ehal/telemetry/{sig.ehal_id}/0{token_q}"
            lines.append(f"  {cmd_name}_on:")
            lines.append(f'    url: "{on_url}"')
            lines.append("    method: GET")
            lines.append(f"  {cmd_name}_off:")
            lines.append(f'    url: "{off_url}"')
            lines.append("    method: GET")
        else:
            # HA automation should pass {{ ehal_value }} after unit conversion in Jinja.
            url = f"{base}/ehal/telemetry/{sig.ehal_id}/" + "{{ ehal_value }}" + token_q
            lines.append(f"  {cmd_name}:")
            lines.append(f'    url: "{url}"')
            lines.append("    method: GET")
            lines.append(f"    # EHAL id: {sig.ehal_id}")

    hb = heartbeat_signal()
    lines.extend(
        [
            "  earnie_push_heartbeat:",
            f'    url: "{base}/ehal/telemetry/{hb.ehal_id}/1{token_q}"',
            "    method: GET",
            "",
            "sensor:",
            "  - platform: rest",
            "    name: earnie_ehal_status",
            f'    resource: "{base}/ehal/status.json{token_q}"',
            "    scan_interval: 10",
            '    value_template: "{{ value_json.heartbeat_ts | default(0) }}"',
            "    json_attributes_path: $",
            "",
        ]
    )
    return "\n".join(lines) + "\n"
