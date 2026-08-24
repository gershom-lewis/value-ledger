"""
Value Ledger — the anti-churn engine.

A small, REUSABLE module that any Eleven Bridges agent plugs into. It records
each unit of work an agent does, tags it with the time and money it saved, and
produces a weekly "here's what your agent did for you" report for the owner.

Why it exists: an agent that silently works gets cancelled; an agent that can
show "I saved you 14 hours and $2,300 this week" gets kept — and upsold. This
turns any agent's activity into a number the client actually feels.

Design (per the Build & Architecture Doctrine):
  - REUSABLE: point it at any agent by adding that agent's value rules to
    value_rules.json. Integrating an agent is two lines (see README).
  - HUMAN-READABLE store: append-only JSONL at data/ledger.jsonl — a plain,
    inspectable source of truth, not a hidden database.
  - READ-ONLY reporting: the weekly report only READS the ledger; it never
    changes an agent or the world. Auto-SENDING the report on a schedule is a
    later step that goes through the automation-hardening gate.
  - NO dependencies: Python standard library only.
"""

import json
import os
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
STORE = os.path.join(DATA_DIR, "ledger.jsonl")
EVENTS_IN = os.path.join(DATA_DIR, "events-in.jsonl")
RULES_PATH = os.path.join(HERE, "value_rules.json")


def _round1(x: float) -> float:
    """Round to 1dp, half-UP and deterministically.

    Python's round() is banker's rounding on top of binary floats, so a total that
    lands exactly on .x5 (1.25 hours does) can come out 1.2 or 1.3 depending on the
    order the numbers were added. A client report whose hours wobble between runs
    is worse than one that is slightly generous - so this pins it."""
    return float(Decimal(repr(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _parse(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.min


def _load_rules() -> dict:
    if os.path.exists(RULES_PATH):
        with open(RULES_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


class ValueLedger:
    """Records value events and reports on them. One ledger per install; agents
    are separated by the `agent` field, so several agents can share one ledger."""

    def __init__(self, store: str = STORE, rules: dict | None = None):
        self.store = store
        self.rules = rules if rules is not None else _load_rules()
        os.makedirs(os.path.dirname(self.store), exist_ok=True)

    # ---------- writing ----------
    def record(self, agent: str, event: str, hours_saved=None, dollars_saved=None,
               note: str = "", count: int = 1, when: datetime | None = None,
               key: str | None = None) -> dict:
        """Record `count` units of `event` done by `agent`. If hours/dollars are
        omitted they're looked up from value_rules.json. Returns the entry."""
        rule = (self.rules.get(agent, {}) or {}).get(event, {})
        hrs = (rule.get("hours", 0) if hours_saved is None else hours_saved) * count
        dol = (rule.get("dollars", 0) if dollars_saved is None else dollars_saved) * count
        entry = {
            "at": (when or datetime.now()).isoformat(timespec="seconds"),
            "agent": agent, "event": event, "label": rule.get("label", event),
            "count": count, "hours_saved": round(hrs, 3), "dollars_saved": round(dol, 2),
            "note": note,
        }
        if key:
            entry["key"] = key
        with open(self.store, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def record_once(self, key: str, agent: str, event: str, **kw):
        """Idempotent record — skips if an entry with this key already exists, so
        adapters can re-run over an agent's logs without double-counting."""
        if key in self._seen_keys():
            return None
        return self.record(agent, event, key=key, **kw)

    # ---------- reading ----------
    def _read_all(self) -> list:
        if not os.path.exists(self.store):
            return []
        rows = []
        with open(self.store, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return rows

    def _seen_keys(self) -> set:
        return {e["key"] for e in self._read_all() if e.get("key")}

    def entries(self, since_days: int | None = None, agent: str | None = None) -> list:
        rows = self._read_all()
        if agent:
            rows = [r for r in rows if r.get("agent") == agent]
        if since_days is not None:
            cutoff = datetime.now() - timedelta(days=since_days)
            rows = [r for r in rows if _parse(r.get("at", "")) >= cutoff]
        return rows

    def rate_for(self, agent: str | None) -> float:
        """The hourly rate to value THIS agent's saved time at. An agent block may
        set its own `_hourly_rate`; otherwise the global default applies.

        This matters for honesty: $150/hr is a consultant's rate. The time an
        agent saves a property manager's office is admin time worth far less, and
        billing it at $150 would inflate the report into something no client
        believes. The whole tool depends on the number being credible."""
        default = (self.rules.get("_defaults", {}) or {}).get("hourly_rate", 150)
        if not agent:
            return default
        return (self.rules.get(agent, {}) or {}).get("_hourly_rate", default)

    def summary(self, since_days: int = 7, agent: str | None = None,
                hourly_rate=None) -> dict:
        rate = hourly_rate or self.rate_for(agent)
        rows = self.entries(since_days=since_days, agent=agent)
        direct = round(sum(r.get("dollars_saved", 0) for r in rows), 2)

        # Value each agent's time at ITS OWN rate, so an all-agents report never
        # blends a $35/hr admin hour into a $150/hr one. Crucially, multiply the
        # ROUNDED per-agent hours - the same figure the report prints - so a client
        # checking "hours x rate" on the page arrives at the number we showed them.
        per_agent = {}
        for r in rows:
            per_agent[r.get("agent")] = per_agent.get(r.get("agent"), 0) + r.get("hours_saved", 0)
        per_agent = {a: _round1(h) for a, h in per_agent.items()}
        hours = _round1(sum(per_agent.values()))
        time_value = round(sum(h * (hourly_rate or self.rate_for(a))
                               for a, h in per_agent.items()), 2)
        by = {}
        for r in rows:
            label = r.get("label", r.get("event"))
            b = by.setdefault(label, {"count": 0, "hours": 0.0, "dollars": 0.0})
            b["count"] += r.get("count", 1)
            b["hours"] += r.get("hours_saved", 0)
            b["dollars"] += r.get("dollars_saved", 0)
        return {
            "agent": agent or "all agents", "days": since_days, "events": len(rows),
            "hours_saved": hours, "direct_dollars": direct, "hourly_rate": rate,
            "time_value": time_value, "total_value": round(direct + time_value, 2),
            "line_items": by,
        }


# ---------- reports ----------
def render_text(s: dict) -> str:
    lines = [
        f"Value Report — {s['agent']} — last {s['days']} days",
        "-" * 48,
        f"  Events logged: {s['events']}",
        f"  Time saved:    {s['hours_saved']} hours",
        f"  Direct value:  ${s['direct_dollars']:,.0f}",
        f"  Time value:    ${s['time_value']:,.0f}  (at ${s['hourly_rate']}/hr equivalent labor)",
        f"  TOTAL VALUE:   ${s['total_value']:,.0f}",
        "  What it did:",
    ]
    for label, b in sorted(s["line_items"].items(), key=lambda kv: -kv[1]["dollars"]):
        lines.append(f"    - {b['count']}x {label}  ->  {round(b['hours'],1)}h / ${b['dollars']:,.0f}")
    if not s["line_items"]:
        lines.append("    (no activity logged in this window)")
    return "\n".join(lines)


def render_html(s: dict, company: str = "Eleven Bridges AI", client: str = "") -> str:
    rows = "".join(
        f"<tr><td>{b['count']}&times;</td><td>{label}</td>"
        f"<td>{round(b['hours'],1)} h</td><td>${b['dollars']:,.0f}</td></tr>"
        for label, b in sorted(s["line_items"].items(), key=lambda kv: -kv[1]["dollars"])
    ) or "<tr><td colspan='4' style='color:#8a91a0'>No activity logged this period.</td></tr>"
    who = f" for {client}" if client else ""
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Value Report — {s['agent']}</title><style>
:root{{--ink:#0B0F14;--paper:#EEF0ED;--muted:#8a91a0;--brass:#C6952F;--red:#D33F2E;--green:#3f9a63;--line:#232836}}
*{{box-sizing:border-box;margin:0;padding:0}}body{{background:#0b0f14;font-family:"Segoe UI",Arial,sans-serif;color:var(--paper);padding:26px 16px}}
.card{{max-width:640px;margin:0 auto;background:#12161d;border:1px solid var(--line);border-radius:14px;overflow:hidden}}
.top{{padding:26px 30px;border-bottom:1px solid var(--line)}}
.kick{{color:var(--brass);font-size:11px;letter-spacing:.22em;text-transform:uppercase;font-weight:700}}
h1{{font-family:Georgia,serif;font-weight:400;font-size:24px;margin-top:8px}}
.sub{{color:var(--muted);font-size:13px;margin-top:6px}}
.hero{{padding:24px 30px;text-align:center;background:linear-gradient(160deg,#12211a,#0f1319)}}
.hero .big{{font-family:Georgia,serif;font-size:44px;color:var(--green);line-height:1}}
.hero .lbl{{color:var(--muted);font-size:12px;letter-spacing:.14em;text-transform:uppercase;margin-top:6px}}
.stats{{display:flex;gap:10px;padding:18px 30px}}
.stat{{flex:1;background:#0f1319;border:1px solid var(--line);border-radius:10px;padding:12px;text-align:center}}
.stat .n{{font-family:Georgia,serif;font-size:22px;color:#fff}}.stat .l{{color:var(--muted);font-size:11px;margin-top:3px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;margin:6px 30px 24px;width:calc(100% - 60px)}}
td{{padding:8px 6px;border-bottom:1px solid var(--line);color:#d7dbe2}}td:first-child{{color:var(--brass);white-space:nowrap}}td:last-child{{text-align:right;color:#fff;font-weight:600}}
.foot{{padding:16px 30px;color:#6a7080;font-size:11.5px;border-top:1px solid var(--line)}}
</style></head><body><div class="card">
<div class="top"><div class="kick">{company} &middot; Weekly Value Report</div>
<h1>{s['agent']} &mdash; what it did{who}</h1>
<div class="sub">Last {s['days']} days &middot; {s['events']} tracked actions</div></div>
<div class="hero"><div class="big">${s['total_value']:,.0f}</div><div class="lbl">Estimated value delivered</div></div>
<div class="stats">
<div class="stat"><div class="n">{s['hours_saved']}h</div><div class="l">Time saved</div></div>
<div class="stat"><div class="n">${s['direct_dollars']:,.0f}</div><div class="l">Direct value</div></div>
<div class="stat"><div class="n">${s['time_value']:,.0f}</div><div class="l">Labor value</div></div>
</div>
<table>{rows}</table>
<div class="foot">Time valued at ${s['hourly_rate']}/hr equivalent manual labor. Evidence-based &mdash; every line is a real logged action. &copy; {company}</div>
</div></body></html>"""


# ---------- event inbox (cloud agents: Savannah, Vannah, ...) ----------
def ingest_events(ledger: "ValueLedger", events_path: str = EVENTS_IN) -> int:
    """Ingest queued agent events from a JSONL inbox — one JSON object per line:
    {"agent": "...", "event": "...", "count"?, "note"?, "at"?, "id"?}.
    A cloud agent (Savannah/Vannah via Make) appends a line per action; this
    records each into the ledger. Idempotent by `id` (or content) so re-running
    never double-counts. Returns the number of NEW events recorded."""
    if not os.path.exists(events_path):
        return 0
    new = 0
    with open(events_path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            agent, event = ev.get("agent"), ev.get("event")
            if not agent or not event:
                continue
            key = ev.get("id") or f"in:{agent}:{event}:{ev.get('at', '')}:{i}"
            when = _parse(ev["at"]) if ev.get("at") else None
            if ledger.record_once(key=key, agent=agent, event=event,
                                  count=int(ev.get("count", 1)),
                                  note=ev.get("note", ""), when=when):
                new += 1
    return new


# ---------- dashboard sync (Command Center "Value" tile) ----------
DASHBOARD_REAL = r"C:\Users\gersh\ai-os-command-center\src\data\real.ts"


def sync_dashboard(summary: dict, real_ts: str = DASHBOARD_REAL) -> bool:
    """Write `summary` into real.ts between the VALUELEDGER markers — mirrors how
    Guardian updates its own block, so the Command Center's Value tile stays fresh.
    Only the marked block changes. Returns False if the file/markers aren't found."""
    import re
    if not os.path.exists(real_ts):
        return False
    with open(real_ts, encoding="utf-8") as fh:
        text = fh.read()
    start, end = "// VALUELEDGER:START", "// VALUELEDGER:END"
    if start not in text or end not in text:
        return False
    items = ",\n".join(
        "    { label: %s, count: %d, hours: %s, dollars: %s }" % (
            json.dumps(label), b["count"], round(b["hours"], 1), round(b["dollars"], 2))
        for label, b in sorted(summary["line_items"].items(), key=lambda kv: -kv[1]["dollars"])
    ) or "    { label: \"No activity yet\", count: 0, hours: 0, dollars: 0 }"
    block = (
        start + " — auto-generated by the Value Ledger adapters (guardian_adapter.py / savannah_adapter.py); do not hand-edit this block.\n"
        "export const valueLedger: ValueLedgerData = {\n"
        f"  agent: {json.dumps(summary['agent'])},\n"
        f"  days: {summary['days']},\n"
        f"  events: {summary['events']},\n"
        f"  hoursSaved: {summary['hours_saved']},\n"
        f"  directDollars: {summary['direct_dollars']},\n"
        f"  timeValue: {summary['time_value']},\n"
        f"  totalValue: {summary['total_value']},\n"
        f"  hourlyRate: {summary['hourly_rate']},\n"
        f"  generatedAt: {json.dumps(datetime.now().strftime('%Y-%m-%d'))},\n"
        "  lineItems: [\n" + items + "\n  ]\n"
        "};\n"
        + end
    )
    new_text = re.sub(re.escape(start) + r".*?" + re.escape(end),
                      lambda _m: block, text, flags=re.DOTALL)
    with open(real_ts, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    return True


if __name__ == "__main__":
    import sys
    import argparse
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows console safety
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Value Ledger — weekly ROI report for an agent")
    ap.add_argument("cmd", nargs="?", default="report", choices=["report", "record"])
    ap.add_argument("--agent")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--event")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--note", default="")
    ap.add_argument("--html", action="store_true")
    a = ap.parse_args()
    L = ValueLedger()
    if a.cmd == "record":
        print("recorded:", L.record(a.agent, a.event, count=a.count, note=a.note))
    else:
        s = L.summary(since_days=a.days, agent=a.agent)
        print(render_text(s))
        if a.html:
            out = os.path.join(HERE, "reports", f"value-report-{(a.agent or 'all').lower()}.html")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(render_html(s))
            print("\nHTML report:", out)
