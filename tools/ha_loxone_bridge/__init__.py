"""Standalone HA <-> Loxone bridge generator (POC: EcoFlow Delta 3).

Reads one JSON mapping file and writes text output only: a Home Assistant package (YAML),
a Loxone Virtual Output template (XML) and a checklist. Nothing is written into a running
HA or Miniserver. No imports from ``ehal/``, ``config.py`` or ``house_config/`` — this
tool must stay extractable into its own repository.

Directions:
  * ``ha_to_loxone``: HA ``rest_command`` writes a Loxone Virtual Input
    (``/jdev/sps/io/<name>/<value>``), triggered by an HA automation.
  * ``loxone_to_ha``: a Loxone Virtual Output command calls an HA webhook
    (``/api/webhook/<id>?v=<v>``); the webhook automation sets the HA entity. No PyLoxone,
    no Virtual Input that mirrors back, hence a single writer per value.
"""
