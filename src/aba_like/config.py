"""Config loading for aba_like.

Everything that could plausibly change between environments (lookback window,
alpha, custom property names, SWIS connection, write-back target) lives here,
not in code, per the "make all thresholds/time windows/model choices
configuration-driven" guardrail.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ResampleConfig:
    interval: str = "1h"
    aggregation: str = "mean"  # mean | max | p95


@dataclass
class BaseThresholdConfig:
    operator: str = ">="
    value: float = 80.0


@dataclass
class AlertConfig:
    mode: str = "anomaly_only"  # anomaly_only | base_plus_anomaly | base_fallback
    bound: str = "both"  # upper | lower | both
    base_threshold: BaseThresholdConfig = field(default_factory=BaseThresholdConfig)
    fallback_to_base_threshold: bool = True
    consecutive_breaches: int = 2
    recovery_margin: float = 0.05
    cooldown_minutes: int = 60
    missing_data_policy: str = "ignore"  # ignore | warning | trigger


@dataclass
class EntityTypeConfig:
    name: str
    swql_entity: str
    id_field: str
    name_field: str
    in_scope_property: str
    in_scope_value: Optional[str] = None


@dataclass
class MetricConfig:
    name: str
    entity_type: str
    source: str
    # Per-metric override of alert.base_threshold — different metrics live on very
    # different scales (a 0-100% CPU load and a response time in ms can't share one
    # threshold), so leaving this unset falls back to the single global default,
    # which is only meaningful for percent-scale metrics.
    base_threshold: Optional[BaseThresholdConfig] = None


@dataclass
class SwisConfig:
    host_env: str = "SWIS_HOST"
    user_env: str = "SWIS_USER"
    password_env: str = "SWIS_PASSWORD"
    port: int = 17774
    verify_ssl: bool = False

    @property
    def host(self) -> str:
        return _require_env(self.host_env)

    @property
    def user(self) -> str:
        return _require_env(self.user_env)

    @property
    def password(self) -> str:
        return _require_env(self.password_env)


@dataclass
class WriteBackConfig:
    enabled: bool = False
    entity_types: list[str] = field(default_factory=lambda: ["node", "interface"])
    property_name: str = "ABA_LIKE_ANOMALY"
    anomaly_value: str = "True"
    normal_value: str = ""


@dataclass
class StorageConfig:
    history_csv: str = "data/history.csv"
    scored_csv: str = "data/scored_latest.csv"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: Optional[str] = None


@dataclass
class Config:
    lookback_days: int = 15  # see config.example.yaml comment: needs to clear lookback_days/7 with margin
    resample: ResampleConfig = field(default_factory=ResampleConfig)
    seasonal_slot: str = "weekday_hour"  # weekday_hour | hour_only | weekday_only
    min_points: int = 2  # see config.example.yaml comment: must stay well under lookback_days/7 for weekday_hour
    alpha: float = 3.0
    nor_method: str = "robust_mad"  # robust_mad (median/MAD, default) | classic_meanstd
    alert: AlertConfig = field(default_factory=AlertConfig)
    entity_types: dict[str, EntityTypeConfig] = field(default_factory=dict)
    metrics: list[MetricConfig] = field(default_factory=list)
    swis: SwisConfig = field(default_factory=SwisConfig)
    write_back: WriteBackConfig = field(default_factory=WriteBackConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    config_dir: Path = field(default_factory=Path.cwd)

    def resolve_path(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (self.config_dir / path)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            "See .env.example for what to set before running."
        )
    return value


def load_config(path: str | Path) -> Config:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    entity_types = {
        key: EntityTypeConfig(name=key, **val)
        for key, val in (raw.get("entity_types") or {}).items()
    }
    metrics = []
    for m in raw.get("metrics") or []:
        m = dict(m)
        if m.get("base_threshold") is not None:
            m["base_threshold"] = BaseThresholdConfig(**m["base_threshold"])
        metrics.append(MetricConfig(**m))

    resample = ResampleConfig(**(raw.get("resample") or {}))

    alert_raw = dict(raw.get("alert") or {})
    base_threshold = BaseThresholdConfig(**(alert_raw.pop("base_threshold", None) or {}))
    alert = AlertConfig(base_threshold=base_threshold, **alert_raw)

    swis = SwisConfig(**(raw.get("swis") or {}))
    write_back = WriteBackConfig(**(raw.get("write_back") or {}))
    storage = StorageConfig(**(raw.get("storage") or {}))
    logging_cfg = LoggingConfig(**(raw.get("logging") or {}))

    cfg = Config(
        lookback_days=raw.get("lookback_days", 14),
        resample=resample,
        seasonal_slot=raw.get("seasonal_slot", "weekday_hour"),
        min_points=raw.get("min_points", 20),
        alpha=raw.get("alpha", 3.0),
        alert=alert,
        entity_types=entity_types,
        metrics=metrics,
        swis=swis,
        write_back=write_back,
        storage=storage,
        logging=logging_cfg,
        config_dir=path.resolve().parent,
    )
    return cfg
