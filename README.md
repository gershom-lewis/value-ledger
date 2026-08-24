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

### Savannah's data stays private (standing decision, 2026-08-24)

**The Savannah Leads sheet is never published to the web** - not the whole sheet,
not a trimmed tab, no variant. "Publish to web" makes a sheet readable by anyone
holding the link, and hers carries real caller names and phone numbers. Her lead
data stays on the machine.

So this install runs **local-file only**: `data/savannah-leads.jsonl`, refreshed
from her Gmail alerts on request. `data/savannah-config.json` is deliberately empty
and carries the same warning.

If a run of hers ever needs to be automated end-to-end, the route is a **Google
service account reading the PRIVATE sheet** - credentials held locally, nothing
exposed. Not the published-CSV path.

*(The `SAVANNAH_SHEET_CSV` / published-CSV capability still exists in the code as a
generic option for client deployments that want it. It is off here and stays off.)*

**Already scheduled:** Windows task **`AIOS Savannah Value Sync`**, daily 07:00, under
`pythonw.exe`. It syncs the local file and refreshes the Command Center Value tile.
Every run appends to `logs/savannah-sync.log`.

```powershell
Get-ScheduledTaskInfo -TaskName "AIOS Savannah Value Sync"   # LastTaskResult 0 = success
```

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

## Setting up a client

See **[SETUP.md](SETUP.md)** — the menu of ways to get an agent's activity in
(direct call, log adapter, event inbox, published sheet, service account, manual),
how to write honest value rules, and how to set a per-client hourly rate.

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
