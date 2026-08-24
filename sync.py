"""
Value Ledger — full sync runner (run this one).

Pulls every agent's activity into the ledger, then refreshes the Command Center
Value tile (whole-team total) and writes the weekly HTML report.

  Guardian                 -> reads its local scan history (guardian_adapter)
  Savannah / Vannah / any  -> queued events in data/events-in.jsonl
                              (their Make scenario appends one line per action;
                               see README "Wiring a cloud agent")

Run:  python sync.py
"""

import os
import sys

from ledger import ValueLedger, ingest_events, render_text, render_html, sync_dashboard
from guardian_adapter import sync as guardian_sync

HERE = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # 1) Guardian scans (real, local)
    _lg, g_new = guardian_sync()
    # 2) Queued cloud-agent events (Savannah, Vannah, ...)
    ledger = ValueLedger()
    e_new = ingest_events(ledger)
    print(f"Synced: {g_new} Guardian scan(s), {e_new} queued event(s).\n")

    # 3) Whole-team summary -> report + dashboard tile
    team = ledger.summary(since_days=7)  # agent=None => all agents
    print(render_text(team))

    out = os.path.join(HERE, "reports", "value-report-team.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_html(team, client="Gershom (self-test)"))
    print("\nHTML report:", out)
    print("Dashboard tile:", "updated" if sync_dashboard(team) else "not updated (markers missing)")
