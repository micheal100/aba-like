# aba_like

A customer-owned, NOR-based anomaly detection proof of concept for SWOSH. It
approximates the *behavior* of SolarWinds Anomaly-Based Alerting (a learned
"normal operating range" band, evaluated per entity/metric on a seasonal
schedule) using a rolling window you control (default **15 days**, unlike
ABA's fixed 7-day window), entirely outside the SolarWinds cloud AIOps
pipeline.

**This is not SolarWinds ABA.** It does not read or write any internal ABA
table or model object, and it does not claim to reproduce SolarWinds'
proprietary cloud model. It only uses the standard, documented SWIS REST API
to read polled metrics and (optionally, later) set a custom property.

## How it works

1. **`fetch`** — pulls raw polled samples from SWIS for every node/interface
   whose custom property marks it in-scope, resamples them to hourly buckets,
   and appends them to a rolling CSV store (`data/history.csv`). Each run
   purges anything older than `lookback_days`, so the store is always a
   rolling window, not an ever-growing file.
2. **`score`** — for every stored point, computes historical median/MAD (or
   mean/stddev) bounds from same-slot history (e.g. "every Monday 9-10am")
   within the lookback window, and flags anomalies.
3. Alert logic layers consecutive-breach, cooldown, hysteresis/recovery
   margin, and a missing-data policy on top, mirroring ABA's own
   `base_condition AND anomaly` composition and untrained-fallback behavior.
4. **`run`** ties fetch+score together and is what you schedule hourly.
   Write-back (setting/clearing a custom property so a normal SolarWinds
   alert can fire on it) is implemented but **disabled by default** — see
   [Write-back](#write-back-long-term) below.

## Setup

```bash
python -m venv .venv
# PowerShell:  .venv\Scripts\Activate.ps1
# cmd.exe:     .venv\Scripts\activate.bat
# bash/WSL:    source .venv/bin/activate
pip install -e ".[dev]"

cp config.example.yaml config.yaml
cp .env.example .env   # then fill in real SWIS_HOST/SWIS_USER/SWIS_PASSWORD values
```

`.env` (gitignored — never commit it) is loaded automatically on every run, from
whatever directory you run `aba-like` in, or from next to `--config` — no
`$env:`/`export`/`source` needed, and it works the same in PowerShell, Git
Bash, WSL, or a Task Scheduler job. A real environment variable (e.g. one set
by Task Scheduler) always takes precedence over `.env`.

Edit `config.yaml`:
- `entity_types.node.in_scope_property` / `entity_types.interface.in_scope_property`
  — the custom property names you use to mark in-scope nodes/interfaces
  (defaults: `In_scope`, `int_in_scope`).
- `lookback_days`, `alpha`, `nor_method` — tune per your testing.
- `swis.verify_ssl: false` is set for a lab self-signed cert; set `true` for
  anything else.

## Try it without SWIS first

```bash
aba-like generate-example --config config.yaml
aba-like score --config config.yaml
aba-like backtest --config config.yaml --report backtest_report.md
```

`generate-example` writes a small synthetic dataset with a stable seasonal
node, a genuine upper-spike node, a genuine lower-spike node, and a cold-start
node with too few points to train — so you can see all four common cases in
`score` output before touching your lab.

## Validating SWQL against your lab

Queries in `src/aba_like/swis_queries.py` have been validated against a real
lab SWOSH instance and differ from generic Orion NPM documentation in a few
ways worth knowing before you point this at a different instance/version:

- No `CustomProperties` navigation property on `Orion.Nodes`/`Orion.NPM.Interfaces`
  here — custom properties are reached with an explicit JOIN to
  `Orion.NodesCustomProperties`/`Orion.NPM.InterfacesCustomProperties` instead.
- The in-scope custom properties turned out to be **boolean**-typed, so
  filtering uses a bare `= true`, not a string comparison.
- Interface traffic bps columns are `InAverageBps`/`OutAverageBps` (no
  underscore, capital B) — the commonly-documented `In_Averagebps` doesn't
  resolve on this instance.
- `Metadata.Property` itself errors on this instance ("Data type
  Metadata.Entity not found"), so `doctor` validates by actually running each
  configured metric query (with a dummy ID and a 1-minute window) rather than
  introspecting metadata.

**Before pointing this at a different instance**, run:

```bash
aba-like doctor --config config.yaml
```

This checks SWIS connectivity, runs every configured metric query for real,
and confirms your custom-property filters return entities. Fix any `[FAIL]`
by editing the corresponding query builder in `swis_queries.py` — everything
is centralized there.

### Memory metric

`memory_used_pct` isn't wired up by default: this lab instance has no generic
per-node historical memory table (`Orion.MemoryUsage` doesn't exist).
The only memory history table found, `Orion.APM.HistoricalMemory`, is keyed
by APM component rather than NodeID, and only has data for nodes/components
the APM module is actively monitoring. If you want memory back:
add a `memory_used_pct` entry to `metrics:` with a `source` that either joins
through APM's Component/Application tables to NodeID (only covers
APM-monitored nodes), or points at whatever custom poller/UnDP your real
environment uses for memory — then validate it with `doctor` before trusting
it.

## Day-to-day commands

```bash
aba-like fetch    --config config.yaml           # pull new samples into the rolling store
aba-like score    --config config.yaml -v        # score + print a table for spot-checking
aba-like run      --config config.yaml --dry-run # fetch + score + log (not apply) write-back
aba-like backtest --config config.yaml --report backtest_report.md --incidents incidents.csv
```

`-v` / `-vv` raise logging verbosity (INFO / DEBUG); `logging.level` in the
config sets the baseline.

### Scheduling hourly

This is deliberately portable (plain `requests`/`pandas`, no OS-specific
dependency). Point either scheduler at `aba-like run --config config.yaml`
(inside the venv):

- **Windows Task Scheduler**: trigger hourly, action
  `C:\Scripts\aba_like\.venv\Scripts\python.exe -m aba_like.cli run --config C:\Scripts\aba_like\config.yaml`,
  with `SWIS_HOST`/`SWIS_USER`/`SWIS_PASSWORD` set on the task's environment.
- **cron / systemd timer** (Linux): `0 * * * * /opt/aba_like/.venv/bin/aba-like run --config /opt/aba_like/config.yaml`.

## Write-back (long-term)

`write_back.enabled: false` by default. When you're ready, create a real
custom property in SWOSH, set:

```yaml
write_back:
  enabled: true
  property_name: YourRealPropertyName
  anomaly_value: "True"
  normal_value: ""
```

and a standard (non-ABA) SolarWinds alert can trigger off that property.
`aba-like run --dry-run` always logs what it *would* set without writing, so
you can verify the mapping before flipping `enabled: true`.

## Validating against native ABA (optional)

If you enable real ABA on a handful of test nodes, you can compare this
script's fired events against native alert history on those same nodes:

```bash
aba-like compare --config config.yaml --nodes 101,102,103 --alert-name-like "%ABA%"
```

This writes `compare_result.csv` — designed to be opened directly in Excel/
Sheets by anyone, not just a developer: plain column headers (`Result`,
`Node`, `Native ABA Time`, `This Tool's Time`, `Minutes Apart`, `This Tool's
Reason`...), readable timestamps, and this tool's own plain-English reason
for firing (or not) alongside each row, so a non-technical reviewer can see
*why* the two disagreed without reading any code. `Result` is one of "Both
flagged this", "Native ABA only", or "This tool only".

The `Orion.AlertHistory`/`Orion.AlertObjects` field names this relies on were
confirmed against a live lab alert (see `src/aba_like/swis_queries.py`), but
re-run `doctor` before trusting it against a different instance/version. This
exists only to sanity-check this script's behavior — it is not a claim of
equivalence to SolarWinds' model.

## A note on statistical confidence at 15 days

With `seasonal_slot: weekday_hour` (168 buckets/week), a slot only recurs
every 7 days, so `lookback_days` needs to clear a multiple of 7 with a bit of
margin before any slot reaches `min_points` — at exactly 14 days, confirmed
empirically against a live lab (0 of ~9,700 scored rows trained), nothing
ever trains. `lookback_days: 15` is the default specifically to clear that
edge with `min_points: 2`.

Even trained, each slot only has ~2 historical samples at 15 days — enough to
demonstrate the mechanics, but a median/MAD of 2 points is noisy, so expect
some false-positive anomalies in early testing. This isn't a bug; it's the
same cold-start tradeoff ABA itself has to manage. Two ways to reduce it
while you're still at ~15 days: raise `alpha`, or temporarily switch
`seasonal_slot` to `hour_only` (24 buckets, ~15 samples/bucket) at the cost of
not distinguishing weekdays from weekends — move back to `weekday_hour` as
`lookback_days` grows toward 60-90 days, where it'll have plenty of samples.

## Performance and scaling

`score`/`run`'s cost is dominated by `models/seasonal_robust.py`'s per-row
scan within each (entity, metric) group — measured directly (synthetic
benchmark, `weekday_hour` slot):

- Scales **linearly with entity count** at a fixed lookback: ~120ms per
  entity/metric group, regardless of how many groups there are. Confirmed
  against a real 42-node/51-interface lab (228 groups, 67k rows): `fetch`
  14s, `score` 30s. Extrapolated: **200 nodes ≈ 75s**; 200 nodes + a future
  500 virtualization hosts (2,100 groups) ≈ 4-5 min. Comfortably inside an
  hourly run either way.
- Scales **quadratically with `lookback_days`** (the per-row scan is
  O(window size) per row): 15d → 115ms/group, 30d → 520ms/group (~4.5x),
  60d → 3,390ms/group (~6.5x more). Extrapolated at 200 nodes: **30 days ≈
  5 min** (still fine), **60 days ≈ 34 min** (cutting it close), **90 days
  would likely exceed an hourly budget outright** — more so once the
  500-VM expansion is added on top.

Not an issue at the current target (200 nodes, 15-30 day lookback). If you
later push toward 60-90 days, revisit `score_history`'s per-row Python loop
first — replacing it with a proper vectorized rolling computation (grouped by
slot, rolling over a time window) is a contained, known fix, deliberately not
done yet since it isn't needed at today's scale.

## Tests

```bash
pytest
```

Covers: stable metric (no alert), upper/lower spikes, expected seasonal peak
(no false alarm), cold-start/untrained state, static-threshold fallback,
MAD=0 quantile fallback, no-look-ahead during backtesting, consecutive-breach
+ cooldown, missing-data policy, and rolling-store dedupe/purge/out-of-order
handling.

## Project layout

```text
src/aba_like/
  config.py            # all tunables: lookback, alpha, custom property names, SWIS, write-back
  swis_client.py        # minimal SWIS REST client (Query/Create/Update/Read)
  swis_queries.py        # SWQL builders — the one place to fix table/field names
  grouping.py            # custom-property based entity discovery
  ingest.py               # fetch + resample pipeline
  store.py                 # rolling CSV history store
  models/seasonal_robust.py # Method A: seasonal median/MAD (or mean/stddev) NOR bands
  alert_logic.py            # consecutive breach, cooldown, hysteresis, missing-data policy
  write_back.py              # generic set/clear custom property (disabled by default)
  reporting.py                # backtest metrics + Markdown report
  compare.py                    # optional: compare vs native ABA/alert history
  doctor.py                      # SWIS connectivity + schema self-check
  synthetic.py                    # generates a demo dataset with no SWIS needed
  cli.py                            # aba-like command line entry point
```

Adding a new entity type later (e.g. virtualization hosts) is a config
change — add an entry under `entity_types` with its SWQL entity/id/name
fields and custom property, plus its metrics under `metrics` — as long as it
exposes a `CustomProperties` navigation property in SWQL.
