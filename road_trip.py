"""
road_trip — turn a list of places you like into an ordered road trip, saved to JSON.

Why this needs a tool at all: same reason as favorites.py — the model has
no memory between conversations. Tell it your stops today, and without
something writing them down, tomorrow's conversation starts from zero.
This stores one ordered stop list per named trip and hands it back on request.

Wire in:

    from road_trip import register
    register(mcp)

Storage: road_trip.json next to this file (override with ROAD_TRIP_DB).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import favorites

DB_PATH = Path(os.environ.get("ROAD_TRIP_DB", Path(__file__).parent / "road_trip.json"))


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
    tmp.replace(DB_PATH)  # atomic — a crash mid-write can't corrupt the file


def register(mcp) -> None:
    @mcp.tool()
    def create_road_trip(trip: str, locations: list[str]) -> str:
        """Save an ordered list of stops as a road trip (replaces any existing one with this name).

        locations: stops in the order you'd visit them, e.g.
        ["San Francisco", "Big Sur", "Los Angeles", "San Diego"].
        """
        if not locations:
            return "Need at least one location to create a road trip."
        db = _load()
        db["trips"][trip] = [{"location": loc, "note": ""} for loc in locations]
        _save(db)
        return f"Created road trip '{trip}' with {len(locations)} stop(s): " + " → ".join(locations)

    @mcp.tool()
    def create_road_trip_from_favorites(trip: str, locations: list[str] | None = None) -> str:
        """Build a road trip directly from your saved favorite locations.

        locations: names to include, in visiting order (matched case-insensitively
        against your favorites, notes carried over). Omit to use every favorite,
        in the order they were saved.
        """
        favs = favorites._load()
        if not favs:
            return "No favorite locations saved yet — add some with add_favorite_location first."
        by_name = {f["name"].lower(): f for f in favs}

        if locations is None:
            chosen = favs
        else:
            chosen = []
            missing = []
            for loc in locations:
                fav = by_name.get(loc.lower())
                if fav is None:
                    missing.append(loc)
                else:
                    chosen.append(fav)
            if missing:
                return f"Not in your favorites: {', '.join(missing)}. Add them first or check spelling."

        db = _load()
        db["trips"][trip] = [{"location": f["name"], "note": f.get("note", "")} for f in chosen]
        _save(db)
        names = [f["name"] for f in chosen]
        return f"Created road trip '{trip}' from favorites with {len(names)} stop(s): " + " → ".join(names)

    @mcp.tool()
    def add_road_trip_stop(trip: str, location: str, note: str = "", position: int | None = None) -> str:
        """Add a stop to an existing (or new) road trip.

        position: 0-based index to insert at; omit to append at the end.
        """
        db = _load()
        stops = db["trips"].setdefault(trip, [])
        entry = {"location": location, "note": note}
        if position is None or position >= len(stops):
            stops.append(entry)
        else:
            stops.insert(max(position, 0), entry)
        _save(db)
        return f"Added '{location}' to '{trip}' ({len(stops)} stop(s) total)."

    @mcp.tool()
    def remove_road_trip_stop(trip: str, location: str) -> str:
        """Remove a stop from a road trip by location name (case-insensitive)."""
        db = _load()
        if trip not in db["trips"]:
            return f"No road trip called '{trip}'."
        stops = db["trips"][trip]
        kept = [s for s in stops if s["location"].lower() != location.lower()]
        if len(kept) == len(stops):
            return f"'{location}' isn't on '{trip}'."
        db["trips"][trip] = kept
        _save(db)
        return f"Removed '{location}' from '{trip}'."

    @mcp.tool()
    def load_road_trip(trip: str) -> str:
        """Load a saved road trip and return its stops in order."""
        db = _load()
        if trip not in db["trips"] or not db["trips"][trip]:
            return f"No road trip called '{trip}' yet."
        stops = db["trips"][trip]
        lines = [f"{i}. {s['location']}" + (f" — {s['note']}" if s.get("note") else "")
                 for i, s in enumerate(stops, start=1)]
        return f"Road trip '{trip}' ({len(stops)} stop(s)):\n" + "\n".join(lines)

    @mcp.tool()
    def list_road_trips() -> str:
        """List the names of all saved road trips."""
        db = _load()
        if not db["trips"]:
            return "No road trips saved yet."
        return "\n".join(f"- {name} ({len(stops)} stop(s))" for name, stops in db["trips"].items())
