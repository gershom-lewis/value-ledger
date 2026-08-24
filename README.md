# Value Ledger

**The anti-churn engine.** A small, reusable module that any Eleven Bridges agent
plugs into. It records what an agent does, tags each action with the time and
money it saved, and produces a weekly *"here's what your agent did for you"*
report for the owner.

Why: an agent that silently works gets cancelled. An agent that can show
*"I saved you 12 hours and $1,800 this week"* gets kept — and upsold. This turns
any agent's activity into a number the client feels.

---

## Proven

Wired to **Guardian** (the read-only network auditor) reading its real scan
history:

```
Value Report — Guardian — last 7 days
  Time saved:  12.0 hours
  TOTAL VALUE: $1,800   (6 scans + 3 issues resolved)
```

Run the full sync (all agents → dashboard tile + report):

```bash
python sync.py
```

That pulls Guardian's scans + any queued cloud-agent events, updates the
Command Center "Value" tile (whole-team total), and writes
`reports/value-report-team.html`.

---

## Savannah — WIRED (2026-08-24)

Savannah is live in the ledger. `savannah_adapter.py` turns her calls into value
events, keyed so a re-run never double-counts.

**Proven on real calls:** 5 calls -> 2 booked AI-efficiency audits, 1 unusable call
screened, 2 off-target callers handled = **$1,180 of value in 30 days**.

She feeds the ledger from either source, both credential-free:

| Path | How | Use when |
|---|---|---|
| **Local file** (default) | `data/savannah-leads.jsonl` — one call per line: `{"id","at","caller","summary"}` | Seeding, backfilling, testing |
| **Published sheet** | Set `SAVANNAH_SHEET_CSV` to the *Publish to web → CSV* link of the **Savannah Leads** sheet Make already writes | Ongoing / unattended |

The published-CSV path is the recommended way to run this unattended: Make already
logs every call to that sheet, so no API key, no OAuth, nothing new to maintain.

```bash
python savannah_adapter.py
```

### Making her self-updating (the one manual step)

1. Open the **Savannah Leads** sheet → **File → Share → Publish to web**
2. Select the **Savannah Leads** tab, format **Comma-separated values (.csv)**, **Publish**
3. Copy the link into `data/savannah-config.json`:

```json
{ "sheet_csv_url": "https://docs.google.com/spreadsheets/d/e/..../pub?gid=0&single=true&output=csv" }
```

That file is gitignored and read at every run — a scheduled task does not inherit
your shell's environment, which is why the URL lives in a file rather than only in
`SAVANNAH_SHEET_CSV`.

**Already scheduled:** Windows task **`AIOS Savannah Value Sync`**, daily 07:00, running
under `pythonw.exe` (no console window). Until the link is set it simply syncs from the
local file — it never invents numbers. A dead or unreachable link degrades to the local
file with a warning; it never breaks the run.

```powershell
Get-ScheduledTaskInfo -TaskName "AIOS Savannah Value Sync"   # LastTaskResult 0 = success
```

Every run appends to `logs/savannah-sync.log`.

**How a call is scored** (`classify()` in the adapter — deliberately conservative,
and deliberately readable):

| Call looks like | Event | Value |
|---|---|---|
| Booked something ("scheduled", "appointment", "audit for") | `appointment-booked` | 0.5h + $500 |
| Real caller with a callback number | `lead-captured` | 0.25h + $200 |
| Off-target / misrouted, correctly turned away | `call-answered` | 0.1h |
| Too short, silent, robocall, wrong number | `spam-screened` | 0.05h |

A call only counts as a *lead* when there is something to follow up on. Misrouted
callers earn `call-answered` — Savannah did real work, but no lead exists. The $500
on a booked appointment is **expected value, not cash**: a booked audit converting at
~25% to a $2,000 assessment. That assumption is written into `value_rules.json` under
`_assumptions` so it is never hidden from a client.

---

## Wiring the next cloud agent (Vannah, …)

Guardian writes a local scan log, so its numbers are read directly. Cloud agents
(Savannah on Vapi, Vannah on Cloudflare) can't write to this machine — so they
drop one line per action into the **event inbox**, `data/events-in.jsonl`:

```json
{"agent": "Savannah", "event": "lead-captured", "id": "vapi-call-abc123", "note": "After-hours call"}
```

- `agent` + `event` must match a block in `value_rules.json` (that's where the
  hours/$ come from). `id` makes it idempotent; `at` (ISO time) and `note` are optional.
- **The one step to go live:** in the agent's **Make** scenario that already fires
  on each call/lead, add a module that appends this line (via a small webhook/sync
  to `events-in.jsonl`, or a shared store you pull from). Then `python sync.py`
  picks it up and it shows on the dashboard — real dollars, not estimates.
- See `data/events-in.example.jsonl` for the format. Until real events flow, a
  cloud agent simply shows nothing — no fake numbers.

---

## Plug in any agent (two ways)

**1. The agent records as it works** — one line wherever the agent does something valuable:

```python
from ledger import ValueLedger
ledger = ValueLedger()
ledger.record("Savannah", "lead-captured", note="After-hours call from Maria")
```

**2. An adapter back-fills from the agent's logs** — see `guardian_adapter.py` as
the template (idempotent, non-invasive, read-only).

Then generate the weekly report:

```bash
python ledger.py report --agent Savannah --days 7 --html
```

---

## Value rules (`value_rules.json`)

Your assumptions, kept honest and visible. For each agent, map an event to the
hours + dollars it saves:

```json
"Savannah": {
  "lead-captured": { "hours": 0.25, "dollars": 200, "label": "Lead captured (would-be missed call)" }
}
```

- `hours` → labor value (hours × `hourly_rate`, default $150).
- `dollars` → direct value (e.g. a captured lead is worth ~$200 to this client).
- Edit per client — every number is an honest, adjustable assumption.

---

## How the value is figured (transparent)

`TOTAL VALUE = direct dollars + (hours saved × hourly rate)`

Every line is a **real logged action** — no invented numbers. "Time value" is
framed as *equivalent manual labor* (what it'd cost a person to do the same
work), not what you charge.

---

## Files

| File | What |
|------|------|
| `ledger.py` | Core module + CLI + text/HTML report. Stdlib only, no dependencies. |
| `value_rules.json` | Per-agent value assumptions (edit per client). |
| `guardian_adapter.py` | Reference adapter — Guardian → ledger. |
| `savannah_adapter.py` | Savannah → ledger (local file or published sheet CSV). |
| `data/savannah-leads.jsonl` | Savannah's known calls (seeded from her Gmail alerts). |
| `data/savannah-config.json` | The published-sheet link for unattended runs (gitignored). |
| `logs/savannah-sync.log` | Every Savannah sync run, appended (gitignored). |
| `data/ledger.jsonl` | The store: append-only, human-readable (gitignored). |
| `reports/` | Generated HTML value reports (gitignored). |

---

## Roadmap

- **Auto-send the weekly report** (email / Telegram) on a schedule → goes through
  the **automation-hardening gate** first (persistence, error handling,
  monitoring, dead-man's switch) before it's called done. Runs manually today.
- ~~**Dashboard tile**~~ — **done.** The Command Center's Guardian page shows a
  "Value Delivered" panel fed by `sync_dashboard()`, covering **all** agents combined.
- **Publish to GitHub** as repo #6 — the package is clean and portfolio-worthy.
- **Per-client branding** on the HTML report.
