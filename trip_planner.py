"""
trip_planner — catch the things a model can't reliably catch while planning a trip.

Design principle (same as meeting_tasks): generating an itinerary is
something the model already does well. What it does badly across a long,
multi-turn planning conversation is: arithmetic over dates and money,
remembering every booking you've locked in, and noticing when two of those
bookings silently conflict. This server does that part.

Wire in:

    from trip_planner import register
    register(mcp)

Storage: one JSON file per install (override with TRIP_PLANNER_DB).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get("TRIP_PLANNER_DB", Path(__file__).parent / "trip_planner.json"))


# ---------------------------------------------------------------- storage

def _load() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"trips": {}}
    try:
        return json.loads(DB_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"trips": {}}


def _save(db: dict[str, Any]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DB_PATH)


def _trip(db: dict[str, Any], name: str) -> dict[str, Any]:
    return db["trips"].setdefault(name, {"budget_cap": None, "currency": None, "items": []})


def _daterange(start: str, end: str):
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    d = d0
    while d < d1:          # end date = checkout/departure day, not a night booked
        yield d
        d += timedelta(days=1)


# -------------------------------------------------------------- the tools

def register(mcp) -> None:
    @mcp.tool()
    def set_trip_budget(trip: str, amount: float, currency: str = "USD") -> str:
        """Set (or update) the total budget cap for a trip."""
        db = _load()
        t = _trip(db, trip)
        t["budget_cap"], t["currency"] = amount, currency
        _save(db)
        return f"Budget for '{trip}' set to {amount:.2f} {currency}."

    @mcp.tool()
    def add_booking(
        trip: str,
        kind: str,
        what: str,
        start_date: str,
        end_date: str | None = None,
        cost: float = 0.0,
        currency: str | None = None,
        refundable: bool = True,
    ) -> str:
        """Record a locked-in booking: flight, lodging, activity, etc.

        kind: "flight" | "lodging" | "activity" | "transport" | "other"
        start_date/end_date: ISO dates. For a same-day item (flight, activity)
        leave end_date empty. For lodging, end_date is the checkout day.

        Immediately checks this booking against everything else already on
        the trip and reports any conflicts — that cross-check is the reason
        this exists instead of just writing it in a note.
        """
        db = _load()
        t = _trip(db, trip)
        end_date = end_date or start_date
        currency = currency or t["currency"] or "USD"

        row = {
            "id": uuid.uuid4().hex[:8],
            "kind": kind,
            "what": what,
            "start": start_date,
            "end": end_date,
            "cost": cost,
            "currency": currency,
            "refundable": refundable,
        }
        conflicts = _find_conflicts(t["items"], row)
        t["items"].append(row)
        _save(db)

        lines = [f"Added [{row['id']}] {kind}: {what} ({start_date} to {end_date}), {cost:.2f} {currency}."]
        if conflicts:
            lines.append("⚠ Conflicts with:")
            for c in conflicts:
                lines.append(f"  [{c['id']}] {c['kind']}: {c['what']} ({c['start']} to {c['end']})"
                             + ("" if c["refundable"] and row["refundable"] else " — at least one side non-refundable"))
        return "\n".join(lines)

    @mcp.tool()
    def trip_status(trip: str) -> str:
        """Budget burn, currency mix, date gaps, and any unresolved conflicts."""
        db = _load()
        if trip not in db["trips"]:
            return f"No trip called '{trip}' yet."
        t = db["trips"][trip]
        items = t["items"]
        if not items:
            return f"'{trip}' has a budget of {t['budget_cap']} {t['currency']} but no bookings yet." \
                   if t["budget_cap"] else f"'{trip}' has no bookings yet."

        by_ccy: dict[str, float] = {}
        for it in items:
            by_ccy[it["currency"]] = by_ccy.get(it["currency"], 0.0) + it["cost"]

        out = [f"Trip '{trip}' — {len(items)} booking(s)."]
        out.append("Spend by currency: " + ", ".join(f"{v:.2f} {c}" for c, v in by_ccy.items()))
        if t["budget_cap"] and t["currency"] in by_ccy:
            spent = by_ccy[t["currency"]]
            remaining = t["budget_cap"] - spent
            pct = spent / t["budget_cap"] * 100 if t["budget_cap"] else 0
            out.append(f"Budget: {spent:.2f}/{t['budget_cap']:.2f} {t['currency']} ({pct:.0f}% used, "
                        f"{remaining:.2f} left)")
        elif t["budget_cap"]:
            out.append(f"Budget cap set ({t['budget_cap']} {t['currency']}) but bookings are in other "
                        f"currencies — total spend not comparable without a conversion rate.")

        conflicts = []
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if _overlaps(a, b) and a["kind"] == b["kind"] == "lodging":
                    conflicts.append((a, b))
                elif _overlaps(a, b) and {a["kind"], b["kind"]} & {"flight", "transport"} and a["kind"] != b["kind"]:
                    pass  # different kinds overlapping same day is normal (flight + activity), skip
        if conflicts:
            out.append("⚠ Unresolved overlaps:")
            for a, b in conflicts:
                out.append(f"  [{a['id']}] {a['what']} overlaps [{b['id']}] {b['what']} "
                            f"({a['start']}–{a['end']} / {b['start']}–{b['end']})")

        lodging = sorted((it for it in items if it["kind"] == "lodging"), key=lambda x: x["start"])
        if lodging:
            covered = set()
            for it in lodging:
                covered |= set(_daterange(it["start"], it["end"]))
            span_start = min(it["start"] for it in lodging)
            span_end = max(it["end"] for it in lodging)
            full_span = set(_daterange(span_start, span_end))
            gaps = sorted(full_span - covered)
            if gaps:
                out.append(f"⚠ No lodging booked for: {', '.join(d.isoformat() for d in gaps)}")

        return "\n".join(out)

    @mcp.tool()
    def cancel_booking(trip: str, booking_id: str) -> str:
        """Remove a booking (e.g. plans changed)."""
        db = _load()
        if trip not in db["trips"]:
            return f"No trip called '{trip}'."
        t = db["trips"][trip]
        before = len(t["items"])
        t["items"] = [it for it in t["items"] if it["id"] != booking_id]
        _save(db)
        return f"Removed [{booking_id}]." if len(t["items"]) < before else f"No booking with id {booking_id}."


def _overlaps(a: dict, b: dict) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def _find_conflicts(existing: list[dict], new: dict) -> list[dict]:
    out = []
    for it in existing:
        if not _overlaps(it, new):
            continue
        # same-kind overlap is always worth flagging (two lodgings, two flights same slot)
        if it["kind"] == new["kind"]:
            out.append(it)
        # lodging vs flight/transport landing outside the booked lodging window is not
        # flagged here — that's a legitimate transit day, not a conflict
    return out
