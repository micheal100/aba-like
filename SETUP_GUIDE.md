# Getting aba-like running on your network

A step-by-step walkthrough for installing and running the ABA-like anomaly
detection tool against your own SolarWinds Platform (SWOSH) instance.
Written for network engineers — no prior Python, Linux, or DevOps experience
assumed.

```
-- Scripts are not supported under any SolarWinds support program or service.
-- Scripts are provided AS IS without warranty of any kind.
-- SolarWinds further disclaims all warranties, including implied warranties
-- of merchantability or fitness for a particular purpose.
-- The risk arising out of the use or performance of the scripts and
-- documentation stays with you.
-- SolarWinds is not liable for damages arising from use of the scripts
-- or documentation.
```

## Contents

1. [What this is](#1-what-this-is)
2. [Before you start](#2-before-you-start)
3. [Get the code](#3-get-the-code)
4. [Install](#4-install)
5. [Configure](#5-configure)
6. [Verify it works](#6-verify-it-works)
7. [Run it every hour](#7-run-it-every-hour)
8. [Reading the results](#8-reading-the-results)
9. [Troubleshooting](#9-troubleshooting)
10. [Support](#10-support)

---

## 1. What this is

**aba-like** is a customer-owned anomaly detection tool built to work
alongside Anomaly-Based Alerting (ABA). ABA itself uses a fixed 7-day
learning window; this tool uses a rolling window *you* control (15, 30, 90
days — your choice), calculated entirely outside SolarWinds' own cloud AIOps
pipeline.

It reads CPU load, response time, packet loss, and interface utilization
from your SolarWinds Platform over the standard SWIS API — the same
interface SolarWinds' own tools use — and never touches any internal ABA
table or model. It runs once an hour, on a schedule you set up.

> **This is not SolarWinds ABA.** It approximates the *behavior* of ABA (a
> learned "normal range," evaluated per metric, per hour-of-week) but does
> not claim to reproduce SolarWinds' proprietary model. Think of it as a
> second, independent opinion running alongside ABA — not a replacement.

## 2. Before you start

Gather these before you begin — every step below assumes you already have
them.

- **A machine to run it on** — either a Windows 10/11 or Windows Server
  machine, *or* a Linux server (Ubuntu 20.04+ or CentOS/RHEL 8+). It only
  needs to reach your SolarWinds server over the network; it doesn't need to
  run on the Orion server itself.
- **Administrator/sudo rights** on that machine, to install Python and set
  up a scheduled task.
- **A SolarWinds service account** — hostname, username, and password for
  an account with read access via SWIS (and eventually write access, if you
  later turn on the optional write-back feature). Ask whoever administers
  your SolarWinds Platform if you don't have one.
- **Rights to create two Custom Properties** in SolarWinds (on Nodes and
  Interfaces) — you'll use these to mark which devices this tool should
  monitor.
- **The project link** — the GitHub repository link your SolarWinds contact
  sent you.

## 3. Get the code

You don't need to know Git to do this — downloading a ZIP file works just as
well.

1. **Open the repository link** in your browser.
2. **Download it.** Click the green **Code** button, then **Download ZIP**.
3. **Extract it somewhere permanent** — not your Downloads folder. For
   example:
   - Windows: `C:\aba-like`
   - Linux: `/opt/aba-like` (or `/home/yourusername/aba-like` if you don't
     have root)

> **Comfortable with git instead?** Anyone on the team who prefers it can
> run `git clone <repository link>` instead of downloading a ZIP — same
> result, and it makes picking up future updates a one-line `git pull`.

## 4. Install

This installs Python's package manager into a private, self-contained
folder inside the project (a "virtual environment") — it won't touch or
conflict with anything else on your machine.

### Windows

**1. Check Python is installed.** Open **PowerShell** (search for it in the
Start menu — do not use Command Prompt), then run:

```powershell
python --version
```

Need at least **3.9**. If that fails, or shows an older version, install
Python from [python.org/downloads/windows](https://www.python.org/downloads/windows/).
During install, **tick "Add python.exe to PATH"** on the first screen — this
is the single most common thing people miss.

**2. Move into the project folder:**

```powershell
cd C:\aba-like
```

**3. Create the virtual environment:**

```powershell
python -m venv .venv
```

**4. Activate it:**

```powershell
.venv\Scripts\Activate.ps1
```

> **If you see a red "running scripts is disabled" error** — Windows blocks
> PowerShell scripts by default. Run the line below (this only loosens the
> rule for your current window, not the whole machine), then retry step 4:
>
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> ```

You'll know it worked because your prompt now starts with `(.venv)`.

**5. Install the tool:**

```powershell
pip install -e ".[dev]"
```

This takes a minute or two — it's downloading a handful of small,
well-known Python libraries (nothing exotic).

**6. Confirm it installed:**

```powershell
aba-like --help
```

You should see a list of commands (`doctor`, `fetch`, `score`, `run`...). If
you do, installation is done — skip to [Configure](#5-configure).

### Ubuntu

**1. Install prerequisites.** Open a terminal and run:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```

You'll be asked for your password (the one you use for `sudo` on this
machine).

**2. Move into the project folder:**

```bash
cd /opt/aba-like
```

**3. Create the virtual environment:**

```bash
python3 -m venv .venv
```

**4. Activate it:**

```bash
source .venv/bin/activate
```

You'll know it worked because your prompt now starts with `(.venv)`.

**5. Install the tool:**

```bash
pip install -e ".[dev]"
```

**6. Confirm it installed:**

```bash
aba-like --help
```

You should see a list of commands. If you do, skip to
[Configure](#5-configure).

### CentOS / RHEL

**1. Install prerequisites.** Open a terminal and run (CentOS/RHEL 8 and 9,
and CentOS Stream, all use `dnf`):

```bash
sudo dnf install -y python3 python3-pip git
```

> **Still on CentOS 7?** CentOS 7 ships Python 3.6, which is too old. Enable
> EPEL first and install Python 3.9 alongside it:
>
> ```bash
> sudo yum install -y epel-release
> sudo yum install -y python39 python39-pip git
> ```
>
> Then use `python3.9` in place of `python3` in the steps below.

**2. Move into the project folder:**

```bash
cd /opt/aba-like
```

**3. Create the virtual environment:**

```bash
python3 -m venv .venv
```

**4. Activate it:**

```bash
source .venv/bin/activate
```

You'll know it worked because your prompt now starts with `(.venv)`.

**5. Install the tool:**

```bash
pip install -e ".[dev]"
```

**6. Confirm it installed:**

```bash
aba-like --help
```

You should see a list of commands. If you do, skip to
[Configure](#5-configure).

## 5. Configure

### A. Tell it how to reach SolarWinds

Copy the credentials template to a real file, then edit it:

**Windows:**
```powershell
copy .env.example .env
notepad .env
```

**Ubuntu / CentOS:**
```bash
cp .env.example .env
nano .env
```

Fill in three values (the SolarWinds contact who gave you this tool can
supply them if you don't have them):

```
SWIS_HOST=your-solarwinds-server-hostname-or-ip
SWIS_USER=your-service-account-username
SWIS_PASSWORD=your-service-account-password
```

Save and close. This file never leaves your machine — it's read locally and
is not sent anywhere else.

### B. Mark which devices to monitor

This tool only looks at nodes and interfaces you explicitly flag, using two
SolarWinds Custom Properties. If they don't already exist in your
environment, create them once:

1. **Open the Custom Property editor.** In the SolarWinds web console:
   **Settings → All Settings → Manage Custom Properties**.
2. **Create a property for Nodes.** Click **Add Custom Property**, choose
   **Node** as the resource type, name it `In_scope`, and set its type to
   **True/False**. Save.
3. **Create a matching one for Interfaces.** Repeat, choosing **Interface**
   as the resource type, named `int_in_scope`, also **True/False**.
4. **Flag the devices you want monitored.** From a Nodes (or Interfaces)
   list view, select the ones you want, right-click → **Edit Custom
   Properties**, and set the property to **True**. Start with a handful —
   you can flag more later at any time.

> **Already using different property names?** That's fine — you don't have
> to rename anything in SolarWinds. Just tell the tool what your existing
> property names are in `config.yaml` (next step):
> `entity_types.node.in_scope_property` and
> `entity_types.interface.in_scope_property`.

### C. Review the settings file

Open `config.yaml` (already in the project folder) in a text editor:

- Windows: `notepad config.yaml`
- Ubuntu / CentOS: `nano config.yaml`

The defaults work as-is for a first test. The two settings worth knowing
about early:

| Setting | What it means |
|---|---|
| `lookback_days` | How many days of history it learns "normal" from. Starts at 15 — the minimum that produces meaningful results; raise it later (30, 60, 90) once you're comfortable. |
| `write_back.enabled` | Stays `false` until you're ready. When `false`, this tool only reads from SolarWinds and writes local report files — it changes nothing in your environment. |

## 6. Verify it works

Run these in order. Each one builds confidence before the next.

**1. Check the connection:**

```
aba-like doctor --config config.yaml
```

Look for a line of green `[OK]` results — connection, your flagged
nodes/interfaces, and every metric query. Anything marked `[FAIL]` or
`[WARN]` tells you exactly what to fix (usually a typo'd hostname, password,
or property name).

**2. Try it without touching real data:**

```
aba-like generate-example --config config.yaml
aba-like score --config config.yaml
```

This builds a small made-up dataset and scores it, so you can see what the
tool's output looks like before it ever talks to your SolarWinds server.

**3. Run it for real:**

```
aba-like fetch --config config.yaml
aba-like score --config config.yaml --only-fired
```

`fetch` pulls your flagged devices' history from SolarWinds. `score
--only-fired` shows only the rows currently flagged as anomalous — likely
nothing yet, since it needs a little history to learn from first.

> **You're set up correctly if...** `doctor` shows all green, and `fetch`
> reports a number of rows written without errors. From here, the only
> thing left is to make it run automatically.

## 7. Run it every hour

The tool doesn't run in the background by itself — you tell your operating
system to run one command, once an hour.

### Windows (Task Scheduler)

1. **Open Task Scheduler.** Search for it in the Start menu.
2. **Create a new task.** In the right-hand panel, click **Create Task**
   (not "Create Basic Task").
3. **Name it.** On the **General** tab, name it `ABA-Like Hourly Run`. Tick
   **Run whether user is logged on or not**.
4. **Set the schedule.** On the **Triggers** tab, click **New**, choose
   **Daily**, then under **Advanced settings** tick **Repeat task every: 1
   hour**, for a duration of **Indefinitely**.
5. **Set the action.** On the **Actions** tab, click **New**:

   | Field | Value |
   |---|---|
   | Program/script | `C:\aba-like\.venv\Scripts\python.exe` |
   | Add arguments | `-m aba_like.cli run --config config.yaml` |
   | Start in | `C:\aba-like` |

6. **Save.** You'll be prompted for your Windows password — this lets the
   task run even when you're not logged in.

> **"Start in" matters.** If you skip the "Start in" field, the task won't
> find `config.yaml` or `.env` and will fail silently. Double-check it's
> set to your project folder.

### Ubuntu / CentOS (cron)

1. **Open your crontab for editing:**

   ```bash
   crontab -e
   ```

   (First time using cron? It may ask you to pick an editor — `nano` is the
   easiest option if offered.)

2. **Add this line** at the bottom, replacing the path with your actual
   project folder:

   ```
   0 * * * * cd /opt/aba-like && ./.venv/bin/aba-like run --config config.yaml >> run.log 2>&1
   ```

3. **Save and exit** (in nano: `Ctrl+O`, then `Enter`, then `Ctrl+X`).

This runs at the top of every hour. Anything the tool prints — including
errors — gets appended to `run.log` in the project folder, so you always
have somewhere to look first.

## 8. Reading the results

Everything the tool produces lands as a plain CSV file in the project's
`data` folder or project root — open any of them directly in Excel. No
developer needed to read these.

| File | What's in it |
|---|---|
| `data/scored_latest.csv` | Every device/metric, its current value, the "normal" range calculated for it, and whether it's flagged — with a plain-English `reason` column explaining why. |
| `backtest_report.md` | A summary report (open in any text editor, or a Markdown viewer) covering the whole history: how many anomalies, how often, and per-device breakdowns. |
| `compare_result.csv` | Only if you run the optional `compare` command against a node with real ABA enabled — lines up this tool's results against native ABA's, side by side. |

## 9. Troubleshooting

**"running scripts is disabled on this system" (Windows)**
PowerShell blocks scripts by default. Run `Set-ExecutionPolicy -Scope
Process -ExecutionPolicy Bypass` in the same window, then try activating
the virtual environment again. This only affects your current window, not
the whole machine.

**`doctor` shows "0 entities matched"**
This means the custom property name in `config.yaml` doesn't match what's
actually set in SolarWinds, or no devices have been flagged `True` yet.
Double-check the property name (case matters) and that at least one
node/interface has it set to True.

**Connection fails, or a certificate error appears**
Check `SWIS_HOST` in `.env` is correct and reachable from this machine (try
pinging it). If your SolarWinds server uses a self-signed certificate
(common in test/lab environments), make sure `swis.verify_ssl` is set to
`false` in `config.yaml`.

**"command not found: aba-like" / "'aba-like' is not recognized"**
Your virtual environment isn't activated in this terminal window. Re-run
the activation command from the [Install](#4-install) step
(`.venv\Scripts\Activate.ps1` on Windows, `source .venv/bin/activate` on
Linux) — you need to do this once per new terminal window, though not for
the scheduled task, which doesn't need activation since it calls the
venv's python.exe directly.

**Nothing shows up as anomalous, even after a day**
This is usually expected early on. The model needs a minimum number of
same-hour, same-weekday history points before it trusts a "normal range"
enough to flag anything — until then, everything reports as "untrained."
Check `data/scored_latest.csv` for the `trained` column; it'll switch to
`True` as history accumulates.

**The scheduled task/cron job doesn't seem to run**
On Windows, open Task Scheduler, select your task, and check the
**History** tab for errors — the most common cause is a wrong "Start in"
folder. On Linux, check `run.log` in the project folder, and confirm with
`crontab -l` that your line was actually saved.

## 10. Support

This is a proof-of-concept tool, not an official SolarWinds product —
there's no support ticket queue for it. For questions, go back to whoever
on the SolarWinds side shared this with you.

```
-- Scripts are not supported under any SolarWinds support program or service.
-- Scripts are provided AS IS without warranty of any kind.
-- SolarWinds further disclaims all warranties, including implied warranties
-- of merchantability or fitness for a particular purpose.
-- The risk arising out of the use or performance of the scripts and
-- documentation stays with you.
-- SolarWinds is not liable for damages arising from use of the scripts
-- or documentation.
```
