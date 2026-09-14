import pandas as pd

from aba_like.store import merge_and_purge


def _row(ts, value):
    return {
        "timestamp": pd.Timestamp(ts, tz="UTC"), "entity_type": "node", "entity_id": 1,
        "entity_name": "n1", "metric_name": "cpu_load_pct", "value": value,
    }


def test_merge_deduplicates_on_same_key_keeping_latest():
    existing = pd.DataFrame([_row("2026-01-01T00:00:00Z", 10.0)])
    new = pd.DataFrame([_row("2026-01-01T00:00:00Z", 99.0)])  # out-of-order re-fetch / correction
    now = pd.Timestamp("2026-01-01T01:00:00Z")
    merged = merge_and_purge(existing, new, lookback_days=14, now=now)
    assert len(merged) == 1
    assert merged.iloc[0]["value"] == 99.0


def test_merge_purges_rows_older_than_lookback():
    old = pd.DataFrame([_row("2025-01-01T00:00:00Z", 10.0)])
    recent = pd.DataFrame([_row("2026-01-01T00:00:00Z", 20.0)])
    now = pd.Timestamp("2026-01-01T01:00:00Z")
    merged = merge_and_purge(old, recent, lookback_days=14, now=now)
    assert len(merged) == 1
    assert merged.iloc[0]["value"] == 20.0


def test_merge_handles_out_of_order_input():
    existing = pd.DataFrame(columns=["timestamp", "entity_type", "entity_id", "entity_name", "metric_name", "value"])
    new = pd.DataFrame([
        _row("2026-01-01T02:00:00Z", 30.0),
        _row("2026-01-01T00:00:00Z", 10.0),
        _row("2026-01-01T01:00:00Z", 20.0),
    ])
    now = pd.Timestamp("2026-01-01T03:00:00Z")
    merged = merge_and_purge(existing, new, lookback_days=14, now=now)
    assert list(merged.sort_values("timestamp")["value"]) == [10.0, 20.0, 30.0]
