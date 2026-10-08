"""
favorites — remember places you like, in a plain JSON file.

Why this needs a tool at all: the model has no memory between
conversations. If you tell it "I love Kyoto in autumn" today, that's gone
tomorrow unless something outside the model writes it down. This is the
simplest version of that fix — one file, one list, read and write.

Wire in:

    from favorites import register
    register(mcp)

Storage: favorites.json next to this file (override with FAVORITES_DB).
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get("FAVORITES_DB", Path(__file__).parent / "favorites.json"))


def _load() -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    try:
        return json.loads(DB_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save(rows: list[dict[str, Any]]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DB_PATH)  # atomic — a crash mid-write can't corrupt the file


def register(mcp) -> None:
    @mcp.tool()
    def add_favorite_location(name: str, note: str = "") -> str:
        """Save a place you like, with an optional note on why.

        Skips silently if the same name (case-insensitive) is already saved,
        so telling the model twice doesn't create duplicates.
        """
        rows = _load()
        if any(r["name"].lower() == name.lower() for r in rows):
            return f"'{name}' is already on the list — not adding a duplicate."
        rows.append({"id": uuid.uuid4().hex[:8], "name": name, "note": note})
        _save(rows)
        return f"Saved '{name}'" + (f" — {note}" if note else "") + "."

    @mcp.tool()
    def list_favorite_locations() -> str:
        """Return every place saved so far, with notes."""
        rows = _load()
        if not rows:
            return "No favorite locations saved yet."
        lines = [f"- {r['name']}" + (f": {r['note']}" if r.get("note") else "") for r in rows]
        return "\n".join(lines)

    @mcp.tool()
    def remove_favorite_location(name: str) -> str:
        """Remove a saved place by name (case-insensitive)."""
        rows = _load()
        kept = [r for r in rows if r["name"].lower() != name.lower()]
        if len(kept) == len(rows):
            return f"'{name}' wasn't on the list."
        _save(kept)
        return f"Removed '{name}'."
