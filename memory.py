"""
memory — keep our conversations in a Neon Postgres database.

Why this needs a tool at all: the model has no memory between
conversations. favorites.py writes to a local JSON file; this writes to
Neon, so the history survives redeploys and is the same wherever the
server runs (laptop or Render).

Wire in:

    from memory import register
    register(mcp)

Storage: the `messages` table in the database at DATABASE_URL.
"""

from __future__ import annotations

import os

import psycopg


def _conn() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set — add your Neon connection string.")
    return psycopg.connect(url)


def _format(rows) -> str:
    return "\n".join(f"[{t:%Y-%m-%d %H:%M}] ({s}) {r}: {c}" for t, s, r, c in rows)


def register(mcp) -> None:
    @mcp.tool()
    def save_message(session_id: str, role: str, content: str) -> str:
        """Store one message of a conversation (role: 'user' or 'assistant')."""
        with _conn() as c:
            c.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
                (session_id, role, content),
            )
        return f"Saved {role} message to session '{session_id}'."

    @mcp.tool()
    def recent_messages(limit: int = 20, session_id: str = "") -> str:
        """Return the most recent messages, optionally only from one session."""
        sql = "SELECT created_at, session_id, role, content FROM messages"
        params: list = []
        if session_id:
            sql += " WHERE session_id = %s"
            params.append(session_id)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with _conn() as c:
            rows = c.execute(sql, params).fetchall()
        return _format(reversed(rows)) or "No messages saved yet."

    @mcp.tool()
    def search_messages(query: str, limit: int = 10) -> str:
        """Search every past conversation for a keyword (case-insensitive)."""
        with _conn() as c:
            rows = c.execute(
                "SELECT created_at, session_id, role, content FROM messages "
                "WHERE content ILIKE %s ORDER BY created_at DESC LIMIT %s",
                (f"%{query}%", limit),
            ).fetchall()
        return _format(rows) or f"No messages mention '{query}'."
