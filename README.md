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

## Wiring a cloud agent (Savannah, Vannah, …)

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
| `data/ledger.jsonl` | The store: append-only, human-readable (gitignored). |
| `reports/` | Generated HTML value reports (gitignored). |

---

## Roadmap

- **Auto-send the weekly report** (email / Telegram) on a schedule → goes through
  the **automation-hardening gate** first (persistence, error handling,
  monitoring, dead-man's switch) before it's called done. Runs manually today.
- **Dashboard tile** — surface "value delivered this week" in the Command Center,
  the same way Guardian's score is surfaced.
- **Per-client branding** on the HTML report.
