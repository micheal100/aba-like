"""Alert logic layered on top of model output.

Composed condition, mirroring the ABA-like "base metric condition AND anomaly
condition" idea described in the build brief:

    if trained:      fire = mode-dependent combination of anomalous/base_condition
    elif fallback:    fire = base_condition
    else:             fire = False

Adds: consecutive-breach requirement, recovery/hysteresis margin (an active
alert must recover past NOR by a margin before it can re-arm, not just touch
the boundary), cooldown, and a missing-data policy. Every row keeps enough
fields (value, bounds, sample_count, reason) to explain itself without
re-running the model.
"""
from __future__ import annotations

import operator

import pandas as pd

from .config import AlertConfig, BaseThresholdConfig, Config

_OPS = {
    ">=": operator.ge, ">": operator.gt,
    "<=": operator.le, "<": operator.lt,
    "==": operator.eq, "!=": operator.ne,
}

OUTPUT_EXTRA_COLUMNS = [
    "anomalous", "base_condition", "condition_met", "fire", "active", "consecutive", "reason",
]


def _check_base_threshold(value: float, bt: BaseThresholdConfig) -> bool:
    op = _OPS.get(bt.operator)
    if op is None:
        raise ValueError(f"Unknown base_threshold operator '{bt.operator}'")
    return bool(op(value, bt.value))


def _bounds_check(value: float, lower: float, upper: float, bound: str) -> tuple[bool, bool]:
    below = value < lower if bound in ("lower", "both") else False
    above = value > upper if bound in ("upper", "both") else False
    return below, above


def _recovered(value: float, lower: float, upper: float, bound: str, margin: float) -> bool:
    """True once value is back inside NOR by `margin` fraction of the band width."""
    width = max(upper - lower, 1e-9)
    pad = margin * width
    lower_ok = value >= lower + pad if bound in ("lower", "both") else True
    upper_ok = value <= upper - pad if bound in ("upper", "both") else True
    return lower_ok and upper_ok


def _reason(
    missing: bool, trained: bool, value, lower, upper, expected, sample_count, min_points,
    anomalous: bool, base_condition: bool, base_cfg: BaseThresholdConfig, condition_met: bool,
    consecutive: int, need: int, in_cooldown: bool, fire: bool, mode: str, policy: str,
) -> str:
    if missing:
        return f"missing data: policy={policy}"
    if not trained:
        base_txt = (
            f"; static fallback base condition ({base_cfg.operator} {base_cfg.value}) "
            f"{'met' if base_condition else 'not met'}"
        )
        return (
            f"model untrained: {sample_count} historical samples available, "
            f"{min_points} required{base_txt if condition_met or fire or base_condition else ''}"
        )

    parts = []
    if anomalous:
        direction = "exceeded upper NOR" if value > upper else "below lower NOR"
        parts.append(f"value {value:.2f} {direction} [{lower:.2f}, {upper:.2f}] (expected {expected:.2f}, n={sample_count})")
    else:
        parts.append(f"value {value:.2f} within NOR [{lower:.2f}, {upper:.2f}] (n={sample_count})")

    if mode in ("base_plus_anomaly", "base_fallback"):
        parts.append(f"base threshold {base_cfg.operator} {base_cfg.value} {'met' if base_condition else 'not met'}")

    if condition_met:
        parts.append(f"consecutive {consecutive}/{need}")
        if in_cooldown:
            parts.append("suppressed by cooldown")
        elif fire:
            parts.append("fired")
    return "; ".join(parts)


def apply_alert_logic(scored: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    if scored.empty:
        return scored.assign(**{c: pd.Series(dtype="object") for c in OUTPUT_EXTRA_COLUMNS})

    alert_cfg = cfg.alert
    metric_thresholds = {
        m.name: m.base_threshold for m in cfg.metrics if m.base_threshold is not None
    }
    df = scored.sort_values(["entity_type", "entity_id", "metric_name", "timestamp"]).copy()

    out_rows = []
    for (_, _, _, metric_name), g in df.groupby(
        ["entity_type", "entity_id", "entity_name", "metric_name"], sort=False
    ):
        base_threshold = metric_thresholds.get(metric_name, alert_cfg.base_threshold)
        g = g.reset_index(drop=True)
        consecutive = 0
        active = False
        cooldown_until: pd.Timestamp | None = None

        for _, row in g.iterrows():
            row = row.to_dict()
            value = row["value"]
            missing = bool(pd.isna(value))

            trained = False if missing else bool(row["trained"])
            lower = None if missing else row["lower_nor"]
            upper = None if missing else row["upper_nor"]
            expected = None if missing else row["expected_value"]
            anomalous = False
            base_condition = False

            if missing:
                # `ignore`/`warning` never contribute to condition_met; `trigger`
                # treats the gap itself as a breach, going through the same
                # consecutive/cooldown/hysteresis machinery as a real breach.
                condition_met = alert_cfg.missing_data_policy == "trigger"
            else:
                base_condition = _check_base_threshold(value, base_threshold)
                if trained:
                    below, above = _bounds_check(value, lower, upper, alert_cfg.bound)
                    anomalous = bool(below or above)
                    if alert_cfg.mode == "anomaly_only":
                        condition_met = anomalous
                    elif alert_cfg.mode == "base_plus_anomaly":
                        condition_met = anomalous and base_condition
                    elif alert_cfg.mode == "base_fallback":
                        condition_met = base_condition
                    else:
                        raise ValueError(f"Unknown alert mode '{alert_cfg.mode}'")
                else:
                    condition_met = bool(alert_cfg.fallback_to_base_threshold and base_condition)

            if active and not missing and trained and _recovered(
                value, lower, upper, alert_cfg.bound, alert_cfg.recovery_margin
            ):
                active = False
                consecutive = 0
            if condition_met:
                consecutive += 1
            else:
                consecutive = 0

            need = alert_cfg.consecutive_breaches
            in_cooldown = cooldown_until is not None and row["timestamp"] < cooldown_until
            fire = condition_met and consecutive >= need and not in_cooldown and not active

            if fire:
                active = True
                cooldown_until = row["timestamp"] + pd.Timedelta(minutes=alert_cfg.cooldown_minutes)
            elif condition_met and consecutive >= need:
                active = True  # stays flagged active even while suppressed by cooldown

            row.update(
                anomalous=anomalous,
                base_condition=base_condition,
                condition_met=condition_met,
                fire=fire,
                active=active,
                consecutive=consecutive,
                reason=_reason(
                    missing, trained, value, lower, upper, expected, row["sample_count"], cfg.min_points,
                    anomalous, base_condition, base_threshold, condition_met,
                    consecutive, need, in_cooldown, fire, alert_cfg.mode, alert_cfg.missing_data_policy,
                ),
            )
            out_rows.append(row)

    return pd.DataFrame(out_rows)
