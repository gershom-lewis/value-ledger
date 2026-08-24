# Setup — plugging a client's agent into the Value Ledger

Every client is different. This is the menu, not a procedure. Pick one row and move on.

---

## Step 1 — how the agent's activity gets in

| # | Option | Credentials? | Use it when |
|---|---|---|---|
| 1 | **The agent records directly** — one `ledger.record()` line where it does the work | none | You built the agent and can edit its code. Cleanest option. |
| 2 | **Adapter reads the agent's own logs** — like `guardian_adapter.py` | none | The agent already writes a log/history file. Read-only, nothing to change in the agent. |
| 3 | **Event inbox** — the agent appends a line to `data/events-in.jsonl` | none | A cloud agent (Make/Zapier/n8n) that can write to a file the machine can see. |
| 4 | **Published sheet CSV** — `sheet_csv_url` in the adapter config | none | The client already logs to a Google Sheet **and is fine with that sheet being readable by anyone holding the link.** |
| 5 | **Private sheet via service account** | Google service account JSON | Same as #4 but the data must stay private. ~30 min setup, then fully automatic. |
| 6 | **Manual refresh** — someone runs the adapter after pasting in records | none | Low volume. Genuinely fine below a few events a week. |

**Option 4 carries a real warning.** "Publish to web" means public to anyone with the URL — no login. Never use it for anything with names, phone numbers, addresses, or balances unless the client explicitly accepts that. *Eleven Bridges' own Savannah is locked to option 6 for exactly this reason.*

**Don't automate before the volume earns it.** Five events a week does not need a scheduler. Automation earns its keep when a report has to land without anyone touching it — which is the point for a paying client, and usually isn't for internal dogfooding.

---

## Step 2 — write the client's value rules

Add a block to `value_rules.json` named for their agent:

```json
"TheirAgent": {
  "_hourly_rate": 35,
  "some-event": { "hours": 0.25, "dollars": 200, "label": "Plain-English description" }
}
```

- **`_hourly_rate` is per agent.** Set it to what the replaced labour actually costs *them* — a leasing assistant is not a $150/hr consultant. Getting this wrong is the fastest way to make a report nobody believes.
- **`label`** is what the client reads on the report. Write it in their words.
- **An event with no rule silently records $0**, so keep event names and rule keys identical.
- **Write the reasoning into `_assumptions`.** Any dollar figure a client might challenge should have its logic visible in the file, not in your head.

### Setting dollar values honestly

- Prefer **expected value** over headline value: a booked appointment isn't cash, it's a chance at cash.
- Anchor to a number the client already knows (their turnover cost, their daily rent, their close rate).
- **Leave the unprovable at $0.** Damage avoided by catching a 2am leak is real and large — and unprovable. One number a client can dispute discredits every other number on the page.
- Start conservative. A modest figure that survives scrutiny beats a big one that collapses in a renewal conversation.

---

## Step 3 — run it

```bash
python your_adapter.py          # sync, print the report, write the HTML
```

Schedule it **only** if step 1 gave you a live feed. On Windows, register a task running `pythonw.exe` (no console window) — and make sure the script survives having no console: under `pythonw`, `sys.stdout` is `None` and an unguarded `print()` crashes the run. See `savannah_adapter.py` for the pattern.

Anything running unattended goes through the automation-hardening gate first.

---

## Step 4 — put the number where they'll see it

- **HTML report** — `reports/value-report-*.html`, brandable per client. This is the weekly email.
- **Dashboard tile** — `sync_dashboard()` writes into The Bridge between the `VALUELEDGER` markers.

Pricing note: this is **included with the managed retainer, never sold separately.** Its job is retention — it pays for itself by making cancellation feel expensive.
