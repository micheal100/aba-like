from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from . import alert_logic, ingest, reporting, store, synthetic, write_back
from .config import Config, load_config
from .doctor import run_doctor
from .logging_setup import setup_logging
from .models.seasonal_robust import score_history
from .swis_client import SwisClient

log = logging.getLogger(__name__)

# Real device data (interface captions, alert messages, etc.) can contain
# characters a Windows console's active codepage can't render. Never let that
# crash a scheduled run — replace what can't be displayed instead.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")


def _load_cfg(args: argparse.Namespace) -> Config:
    # Load .env for SWIS_HOST/SWIS_USER/SWIS_PASSWORD so no shell-specific env var
    # syntax (PowerShell $env:, bash export, etc.) is needed. Never overrides a
    # variable already set in the real environment (e.g. by Task Scheduler/cron).
    load_dotenv()  # searches upward from the current working directory
    config_path = Path(args.config)
    load_dotenv(config_path.resolve().parent / ".env")  # also try next to --config

    cfg = load_config(args.config)
    setup_logging(cfg.logging, verbosity=args.verbose)
    return cfg


def _print_score_table(alerted: pd.DataFrame, only_fired: bool = False, max_rows: int = 50) -> None:
    view = alerted[alerted["fire"]] if only_fired else alerted
    cols = [
        "timestamp", "entity_type", "entity_name", "metric_name", "value",
        "lower_nor", "upper_nor", "expected_value", "trained", "sample_count",
        "anomalous", "fire", "reason",
    ]
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(view[cols].tail(max_rows).to_string(index=False))


def cmd_generate_example(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args)
    df = synthetic.generate_history(lookback_days=cfg.lookback_days)
    out_path = cfg.resolve_path(args.output or cfg.storage.history_csv)
    store.save_history(out_path, df)
    print(f"Wrote {len(df)} synthetic rows to {out_path}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args)
    client = SwisClient(cfg.swis)
    ok = run_doctor(client, cfg)
    return 0 if ok else 1


def cmd_fetch(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args)
    client = SwisClient(cfg.swis)

    history_path = cfg.resolve_path(cfg.storage.history_csv)
    existing = store.load_history(history_path)

    now = pd.Timestamp.now(tz="UTC").floor(cfg.resample.interval)
    last_ts = store.last_timestamp(existing)
    start = last_ts if last_ts is not None else now - pd.Timedelta(days=cfg.lookback_days)
    if start >= now:
        print("Store already up to date; nothing to fetch.")
        return 0

    entities = ingest.discover_all_entities(client, cfg)
    for etype, ents in entities.items():
        if not ents:
            log.warning("No in-scope %s entities discovered - check custom property config", etype)

    raw = ingest.fetch_raw_samples(client, cfg, entities, start, now)
    resampled = ingest.resample_to_interval(raw, cfg.resample.interval, cfg.resample.aggregation)

    merged = store.merge_and_purge(existing, resampled, cfg.lookback_days, now)
    store.save_history(history_path, merged)
    print(f"Fetched {len(resampled)} new points ({start} .. {now}); store now has {len(merged)} rows.")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args)
    history_path = cfg.resolve_path(cfg.storage.history_csv)
    history = store.load_history(history_path)
    if history.empty:
        print(f"No history found at {history_path}. Run `fetch` or `generate-example` first.", file=sys.stderr)
        return 1

    scored = score_history(history, cfg)
    alerted = alert_logic.apply_alert_logic(scored, cfg)

    out_path = cfg.resolve_path(args.output or cfg.storage.scored_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    alerted.to_csv(out_path, index=False)
    print(f"Scored {len(alerted)} rows -> {out_path}\n")

    _print_score_table(alerted, only_fired=args.only_fired)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    rc = cmd_fetch(args)
    if rc != 0:
        return rc
    cfg = _load_cfg(args)
    history = store.load_history(cfg.resolve_path(cfg.storage.history_csv))
    scored = score_history(history, cfg)
    alerted = alert_logic.apply_alert_logic(scored, cfg)

    out_path = cfg.resolve_path(cfg.storage.scored_csv)
    alerted.to_csv(out_path, index=False)

    latest = alerted.sort_values("timestamp").groupby(
        ["entity_type", "entity_id", "metric_name"], as_index=False
    ).tail(1)
    fired_now = latest[latest["fire"]]
    if not fired_now.empty:
        print(f"{len(fired_now)} alert(s) firing this run:")
        _print_score_table(fired_now, only_fired=True)
    else:
        print("No alerts firing this run.")

    # A client is needed even for a dry-run preview: looking up an entity's real
    # URI to show what *would* be written is a read, not a write.
    client = SwisClient(cfg.swis)
    write_back.apply_write_back(client, cfg, alerted, dry_run=args.dry_run or not cfg.write_back.enabled)
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args)
    history = store.load_history(cfg.resolve_path(cfg.storage.history_csv))
    if history.empty:
        print(f"No history found. Run `fetch` or `generate-example` first.", file=sys.stderr)
        return 1

    scored = score_history(history, cfg)
    alerted = alert_logic.apply_alert_logic(scored, cfg)

    incidents = None
    if args.incidents:
        incidents = pd.read_csv(args.incidents)

    metrics = reporting.compute_metrics(alerted, incidents)

    report_path = cfg.resolve_path(args.report or "backtest_report.md")
    csv_path = cfg.resolve_path(args.output or "backtest_per_entity.csv")
    reporting.write_report(metrics, cfg, report_path, csv_path)

    print(f"Backtest report -> {report_path}")
    print(f"Per-entity/metric CSV -> {csv_path}")
    print(f"\nTotal observations: {metrics['total_observations']}, fired alerts: {metrics['fired_alerts']}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    from . import compare as compare_mod

    cfg = _load_cfg(args)
    scored_path = cfg.resolve_path(args.scored or cfg.storage.scored_csv)
    if not scored_path.exists():
        print(f"No scored file at {scored_path}; run `score` first.", file=sys.stderr)
        return 1
    ours = pd.read_csv(scored_path, parse_dates=["timestamp"])

    node_ids = [int(x) for x in args.nodes.split(",")]
    # Native alert history is always node-scoped (RelatedNodeId); restrict to node-type
    # rows for the requested nodes only. Without this, entity_id collisions between
    # nodes and interfaces (both are plain small integers) could cross-match, and
    # fire events from unrelated nodes would pollute the "ours_only" count.
    ours = ours[(ours["entity_type"] == "node") & (ours["entity_id"].isin(node_ids))]
    client = SwisClient(cfg.swis)
    start = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=cfg.lookback_days)
    end = pd.Timestamp.now(tz="UTC")

    native = compare_mod.fetch_native_alert_events(client, node_ids, start, end, args.alert_name_like)
    result = compare_mod.compare_events(native, ours, tolerance_minutes=args.tolerance_minutes)

    out_path = cfg.resolve_path(args.output or "compare_result.csv")
    result.to_csv(out_path, index=False)
    print(f"Compared {len(native)} native alert events vs our fired events -> {out_path}")
    if not result.empty:
        print(result["match"].value_counts().to_string())
    return 0


def build_parser() -> argparse.ArgumentParser:
    # Shared options that work both before and after the subcommand, e.g.
    # `aba-like --config c.yaml score` and `aba-like score --config c.yaml`.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config.yaml", help="Path to config YAML (default: config.yaml)")
    common.add_argument("-v", "--verbose", action="count", default=0, help="-v for INFO+, -vv for DEBUG")

    p = argparse.ArgumentParser(prog="aba-like", description=__doc__, parents=[common])
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser(
        "generate-example", parents=[common],
        help="Write a synthetic history CSV for local testing (no SWIS needed)",
    )
    sp.add_argument("--output", help="Override storage.history_csv path")
    sp.set_defaults(func=cmd_generate_example)

    sp = sub.add_parser(
        "doctor", parents=[common], help="Check SWIS connectivity, schema assumptions, and entity discovery",
    )
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("fetch", parents=[common], help="Pull new samples from SWIS into the rolling history store")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("score", parents=[common], help="Score the current history store and print/export results")
    sp.add_argument("--output", help="Override storage.scored_csv path")
    sp.add_argument("--only-fired", action="store_true", help="Only print rows where fire=True")
    sp.set_defaults(func=cmd_score)

    sp = sub.add_parser(
        "run", parents=[common],
        help="fetch + score + (optional) write-back - intended for hourly scheduling",
    )
    sp.add_argument("--dry-run", action="store_true", help="Never write to SWIS, just log what would happen")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser(
        "backtest", parents=[common],
        help="Score the full stored history chronologically and produce a report",
    )
    sp.add_argument("--report", help="Markdown report output path (default: backtest_report.md)")
    sp.add_argument("--output", help="Per-entity/metric CSV output path (default: backtest_per_entity.csv)")
    sp.add_argument("--incidents", help="Optional incident CSV: timestamp_start,timestamp_end,entity_id,metric_name,label,notes")
    sp.set_defaults(func=cmd_backtest)

    sp = sub.add_parser(
        "compare", parents=[common],
        help="Optional: compare fired events against native SolarWinds alert/ABA history on test nodes",
    )
    sp.add_argument("--nodes", required=True, help="Comma-separated NodeIDs enabled for native ABA testing")
    sp.add_argument("--alert-name-like", help="SQL LIKE pattern to filter native alert definitions, e.g. %%ABA%%")
    sp.add_argument("--scored", help="Path to a previously-written scored CSV (default: storage.scored_csv)")
    sp.add_argument("--tolerance-minutes", type=int, default=30)
    sp.add_argument("--output", help="Comparison CSV output path (default: compare_result.csv)")
    sp.set_defaults(func=cmd_compare)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
