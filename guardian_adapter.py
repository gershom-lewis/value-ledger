"""
Guardian -> Value Ledger adapter.

Reads Guardian's scan snapshots (guardian/reports/history/scan-*.json) and
records one value event per scan into the Value Ledger, plus an event for each
newly-resolved finding. Idempotent (keyed by the snapshot filename), so it can
be re-run safely. Non-invasive: it only READS Guardian's output — it never
touches Guardian or the network.

This is the reference example of plugging an agent into the ledger. For a
client agent (Savannah, Vannah, ...) you write a similar tiny adapter, or the
agent calls ledger.record(...) directly as it works.

Run:  python guardian_adapter.py      (syncs, prints the report, writes HTML)
"""

import glob
import json
import os
import sys
from datetime import datetime

from ledger import ValueLedger, render_text, render_html, sync_dashboard

GUARDIAN_HISTORY = r"C:\Users\gersh\guardian\reports\history"


def _when(iso: str) -> datetime:
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        return datetime.now()


def sync(history_dir: str = GUARDIAN_HISTORY):
    """Back-fill the ledger from Guardian's scan history. Returns (ledger, new_count)."""
    ledger = ValueLedger()
    files = sorted(glob.glob(os.path.join(history_dir, "scan-*.json")))
    new = 0
    prev_findings = set()
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                snap = json.load(fh)
        except Exception:
            continue
        stamp = os.path.basename(path)
        when = _when(snap.get("capturedAt", ""))
        devices = len(snap.get("devices", []))
        score = snap.get("score")
        entry = ledger.record_once(
            key=f"guardian:{stamp}", agent="Guardian", event="security-scan",
            when=when, note=f"score {score}/100, {devices} devices audited")
        if entry:
            new += 1
        curr = {(x.get("area"), x.get("title")) for x in snap.get("findings", [])}
        for _area, title in (prev_findings - curr):
            ledger.record_once(
                key=f"guardian:{stamp}:resolved:{title}", agent="Guardian",
                event="issue-resolved", when=when, note=f"Resolved: {title}")
        prev_findings = curr
    return ledger, new


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ledger, n = sync()
    print(f"Synced Guardian history -> {n} new scan event(s) recorded.\n")
    summary = ledger.summary(since_days=7, agent="Guardian")
    print(render_text(summary))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports",
                       "value-report-guardian.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_html(summary, client="Gershom (self-test)"))
    print("\nHTML report:", out)
    print("(For the team dashboard tile, run: python sync.py)")
