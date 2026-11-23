"""EHAL-Com warning text for energy counters too coarse for quarter-hour Ist."""
from __future__ import annotations

from ui.coarse_counter_warning import coarse_counter_warning_text


def test_no_warning_without_coarse_counters():
    assert coarse_counter_warning_text({}) is None


def test_warning_names_each_counter_and_the_fix():
    consumers = [{"id": "trockner", "name": "Trockner", "type": "generic"}]
    text = coarse_counter_warning_text(
        {"pv": "2026-11-23T18:00:00", "flex:trockner": "2026-11-23T18:00:00"},
        consumers,
    )
    assert text is not None
    assert "bitte handeln" in text
    assert "`sens_pv_energy`" in text
    assert "Trockner (`consumer.trockner.sens_energy_total`)" in text
    assert "zuletzt 2026-11-23 18:00:00" in text
    assert "`<v.3>`" in text
