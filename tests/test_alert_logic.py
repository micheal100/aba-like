import numpy as np
import pandas as pd

from aba_like.alert_logic import apply_alert_logic
from aba_like.config import AlertConfig, BaseThresholdConfig, Config
from aba_like.models.seasonal_robust import score_history


def _history(values, start="2026-01-05T00:00:00Z"):
    idx = pd.date_range(start, periods=len(values), freq="1h", tz="UTC")
    return pd.DataFrame({
        "timestamp": idx, "entity_type": "node", "entity_id": 1,
        "entity_name": "n1", "metric_name": "cpu_load_pct", "value": values,
    })


def _cfg(**alert_overrides) -> Config:
    defaults = dict(consecutive_breaches=2, cooldown_minutes=180, recovery_margin=0.05)
    defaults.update(alert_overrides)
    alert = AlertConfig(**defaults)
    return Config(lookback_days=14, min_points=5, alpha=3.0, seasonal_slot="hour_only", alert=alert)


def test_consecutive_breaches_and_cooldown():
    rng = np.random.default_rng(0)
    base = list(50 + rng.normal(0, 1, 40))
    # two consecutive breaches, then a third right after (should be cooled down)
    values = base + [95.0, 96.0, 97.0]
    history = _history(values)
    cfg = _cfg()
    scored = score_history(history, cfg)
    alerted = apply_alert_logic(scored, cfg)

    tail = alerted.tail(3).reset_index(drop=True)
    assert tail.loc[0, "fire"] == False  # 1st breach: consecutive=1 < 2
    assert tail.loc[1, "fire"] == True   # 2nd consecutive breach fires
    assert tail.loc[2, "fire"] == False  # still active/in cooldown, suppressed


def test_missing_data_policy_ignore_does_not_fire():
    values = [50.0] * 30
    history = _history(values)
    # Inject a NaN "gap" row for the most recent timestamp
    history.loc[len(history) - 1, "value"] = np.nan
    cfg = _cfg(missing_data_policy="ignore")
    scored = score_history(history, cfg)
    alerted = apply_alert_logic(scored, cfg)
    last = alerted.iloc[-1]
    assert last["fire"] == False
    assert "missing data" in last["reason"]


def test_missing_data_policy_trigger_fires():
    values = [50.0] * 30
    history = _history(values)
    history.loc[len(history) - 1, "value"] = np.nan
    cfg = _cfg(missing_data_policy="trigger", consecutive_breaches=1)
    scored = score_history(history, cfg)
    alerted = apply_alert_logic(scored, cfg)
    last = alerted.iloc[-1]
    assert last["fire"] == True


def test_untrained_static_fallback_can_fire():
    values = [50.0, 52.0, 95.0]  # too few points to train
    history = _history(values)
    alert = AlertConfig(
        consecutive_breaches=1, fallback_to_base_threshold=True,
        base_threshold=BaseThresholdConfig(operator=">=", value=80),
    )
    cfg = Config(lookback_days=14, min_points=20, alert=alert)
    scored = score_history(history, cfg)
    alerted = apply_alert_logic(scored, cfg)
    last = alerted.iloc[-1]
    assert last["trained"] == False
    assert last["fire"] == True
    assert "untrained" in last["reason"]


def test_untrained_without_fallback_never_fires():
    values = [50.0, 52.0, 95.0]
    history = _history(values)
    alert = AlertConfig(consecutive_breaches=1, fallback_to_base_threshold=False)
    cfg = Config(lookback_days=14, min_points=20, alert=alert)
    scored = score_history(history, cfg)
    alerted = apply_alert_logic(scored, cfg)
    assert not alerted["fire"].any()
