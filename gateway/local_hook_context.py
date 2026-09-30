"""Read-only, SQLite FTS context retrieval for explicitly installed client hooks."""

from __future__ import annotations

import re
import sqlite3
import threading
from typing import Any, Callable


def search_context(
    connection: sqlite3.Connection,
    lock: threading.RLock,
    message: str,
    *,
    focus_query: Callable[[str], str],
    language: str,
    eligible_ids: set[str],
    limit: int = 3,
) -> dict[str, Any]:
    """Return a small provenance-preserving packet using local FTS tables only.

    This path deliberately does not call embedding, reranking, provider, model,
    or telemetry services. Query and result text are not returned as diagnostics.
    """
    bounded_limit = max(1, min(int(limit), 3))
    allowed_ids = sorted({str(value).strip() for value in eligible_ids if str(value).strip()})[:100]
    if not allowed_ids:
        return {"context_packet": [], "limit": bounded_limit}
    normalized = re.sub(r"\s+", " ", str(message or "").strip())[:2000]
    focus = focus_query(normalized) if normalized else ""
    tokens = re.findall(r"[\w'-]+", str(focus or ""))[:8]
    tokens = [token for token in tokens if token]
    if not tokens:
        return {"context_packet": [], "limit": bounded_limit}

    match = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
    allowed_clause = ",".join("?" for _ in allowed_ids)
    rows: list[sqlite3.Row] = []
    seen_ids: set[str] = set()
    with lock:
        try:
            primary = connection.execute(
                "SELECT m.id,m.kind,m.text,m.source,m.occurred_at,m.created_at "
                "FROM memory_fts f JOIN memories m ON m.rowid=f.rowid "
                f"WHERE m.archived=0 AND m.id IN ({allowed_clause}) AND memory_fts MATCH ? "
                "ORDER BY bm25(memory_fts),m.updated_at DESC LIMIT ?",
                (*allowed_ids, match, 50),
            ).fetchall()
        except sqlite3.OperationalError:
            primary = []
        for row in primary:
            memory_id = str(row["id"])
            if memory_id not in seen_ids:
                seen_ids.add(memory_id)
                rows.append(row)
                if len(rows) >= bounded_limit:
                    break

        if len(rows) < bounded_limit and language in {"ar", "en"}:
            try:
                localized = connection.execute(
                    "SELECT DISTINCT m.id,m.kind,m.text,m.source,m.occurred_at,m.created_at "
                    "FROM memory_localized_fts f JOIN memories m ON m.id=f.memory_id "
                    f"WHERE m.archived=0 AND m.id IN ({allowed_clause}) "
                    "AND f.language=? AND memory_localized_fts MATCH ? "
                    "ORDER BY bm25(memory_localized_fts),m.updated_at DESC LIMIT ?",
                    (*allowed_ids, language, match, 50),
                ).fetchall()
            except sqlite3.OperationalError:
                localized = []
            for row in localized:
                memory_id = str(row["id"])
                if memory_id not in seen_ids:
                    seen_ids.add(memory_id)
                    rows.append(row)
                    if len(rows) >= bounded_limit:
                        break

    packet = [
        {
            "type": str(row["kind"] or "fact")[:40],
            "text": str(row["text"] or "")[:1200],
            "source": str(row["source"] or "")[:80],
            "date": str(row["occurred_at"] or row["created_at"] or "")[:40],
        }
        for row in rows
        if str(row["text"] or "").strip()
    ]
    return {"context_packet": packet, "limit": bounded_limit}
