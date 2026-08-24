"""
Savannah -> Value Ledger adapter.

Savannah is the AI receptionist on H1's 800 number (Vapi). Every call already
fans out three ways through Make.com: Telegram alert, Gmail alert, and a
"Savannah Leads" Google Sheet row. This adapter turns those calls into value
events so the weekly report shows real lead dollars instead of $0.

Two input paths, both credential-free:

  1. LOCAL FILE (default) - data/savannah-leads.jsonl, one JSON object per line:
       {"id": "...", "at": "2026-08-19T15:22:46", "caller": "+1...", "summary": "..."}

  2. PUBLISHED SHEET (for unattended running) - set SAVANNAH_SHEET_CSV to the
     "Publish to web -> CSV" link of the Savannah Leads sheet. No API key, no
     OAuth. Columns are matched loosely by header name
     (date / caller / summary / status).

Idempotent: every call is keyed, so re-running never double-counts.
Read-only: it never touches Savannah, Vapi, or Make.

Run:  python savannah_adapter.py
"""

import csv
import io
import json
import os
import sys
import urllib.request
from datetime import datetime

from ledger import ValueLedger, render_text, render_html, sync_dashboard

HERE = os.path.dirname(os.path.abspath(__file__))
LEADS_FILE = os.path.join(HERE, "data", "savannah-leads.jsonl")
SHEET_CSV = os.environ.get("SAVANNAH_SHEET_CSV", "").strip()

# Phrases that decide what a call was worth. Kept here, in the open, because
# they are judgement calls - not hidden scoring.
BOOKED = ("scheduled", "booked", "appointment", "set up a call", "audit for")
UNUSABLE = ("too short", "no information", "unable to extract", "silent",
            "robocall", "spam", "wrong number", "test call")
MISROUTED = ("not a real estate", "informed this is an ai company",
             "not a real estate service", "does not offer")


def _parse_when(s):
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(s)[:19], fmt)
        except Exception:
            continue
    return datetime.now()


def classify(summary, caller=""):
    """Map a call summary to (event, note). Conservative on purpose: a call only
    counts as a lead when there is something to follow up on."""
    s = (summary or "").lower()

    if any(k in s for k in UNUSABLE):
        return "spam-screened", "Unusable call screened out"

    if any(k in s for k in BOOKED):
        return "appointment-booked", "Booked from the call"

    if any(k in s for k in MISROUTED):
        # Savannah answered and correctly turned away an off-target caller.
        # Real work, no lead - so it earns call-answered, not lead-captured.
        return "call-answered", "Off-target caller handled"

    has_callback = "no callback" not in s and bool(caller)
    if has_callback:
        return "lead-captured", "Caller with callback number"
    return "call-answered", "Call answered, no callback captured"


def _load_local(path=LEADS_FILE):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  ! skipped malformed line {i + 1} in {os.path.basename(path)}")
    return rows


def _load_sheet(url=SHEET_CSV):
    """Read the published-to-web CSV of the Savannah Leads sheet."""
    if not url:
        return []
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  ! could not read the published sheet ({e}) - using local file only")
        return []

    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        low = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}

        def pick(*names):
            for n in names:
                for k, v in low.items():
                    if n in k and v:
                        return v
            return ""

        at = pick("date", "time", "when")
        caller = pick("caller", "phone", "number", "from")
        summary = pick("summary", "notes", "transcript", "detail")
        if not (at or caller or summary):
            continue
        rows.append({"id": f"sheet:{at}:{caller}", "at": at,
                     "caller": caller, "summary": summary})
    return rows


def sync():
    """Record every known Savannah call into the ledger. Returns (ledger, new_count)."""
    ledger = ValueLedger()
    rows = _load_local() + _load_sheet()

    # De-duplicate across both sources on caller+timestamp.
    seen, calls = set(), []
    for r in rows:
        sig = (str(r.get("caller", "")).strip(), str(r.get("at", ""))[:16])
        if sig in seen:
            continue
        seen.add(sig)
        calls.append(r)

    new = 0
    for r in calls:
        summary = r.get("summary", "")
        caller = r.get("caller", "")
        event, why = classify(summary, caller)
        key = r.get("id") or f"savannah:{caller}:{r.get('at', '')}"
        note = f"{why}: {summary[:160]}" if summary else why
        if ledger.record_once(key=f"savannah:{key}", agent="Savannah", event=event,
                              when=_parse_when(r.get("at")), note=note):
            new += 1
    return ledger, new, calls


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ledger, n, calls = sync()
    print(f"Synced Savannah -> {len(calls)} call(s) known, {n} new event(s) recorded.\n")

    for r in calls:
        ev, _ = classify(r.get("summary", ""), r.get("caller", ""))
        print(f"  {str(r.get('at', ''))[:10]}  {r.get('caller', ''):<15} {ev}")

    # 30 days: Savannah's real calls are older than the default 7-day window,
    # so a 7-day report would honestly read $0.
    print()
    summary = ledger.summary(since_days=30, agent="Savannah")
    print(render_text(summary))

    out = os.path.join(HERE, "reports", "value-report-savannah.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_html(summary, client="H1 Enterprises (self-test)"))
    print("\nHTML report:", out)

    # The dashboard tile shows ALL agents combined (Guardian + Savannah).
    combined = ledger.summary(since_days=30)
    if sync_dashboard(combined):
        print("Dashboard Value tile updated (all agents, 30 days).")
    else:
        print("Dashboard tile NOT updated - real.ts or its VALUELEDGER markers were not found.")
