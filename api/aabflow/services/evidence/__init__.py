"""Evidence lookup and SQLite FTS5 search over curated content (T3.3, T11.6).

Corpus: every published pilot's ``evidence.json`` records, the methodology
chunks, metric definitions and the intervention catalog. The index is rebuilt
when the corpus hash changes. Search results are bounded and returned as data.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from aabflow.domain.hashes import content_hash
from aabflow.domain.schemas import EvidenceRecord
from aabflow.services.evidence.methodology import METHODOLOGY
from aabflow.services.pilots import PilotRepository

MAX_RESULTS = 25
SNIPPET_TOKENS = 24


def _record_text(rec: EvidenceRecord) -> str:
    parts = [
        rec.source_title,
        rec.kind.value,
        rec.transformation or "",
        rec.geographic_scope or "",
        rec.source_period or "",
        rec.units or "",
        rec.allowed_use or "",
        " ".join(rec.limitations),
        rec.source_asset_id or "",
    ]
    return " ".join(p for p in parts if p)


def corpus(pilots: PilotRepository) -> list[dict[str, Any]]:
    from aabflow.services.metrics import REGISTRY

    docs: list[dict[str, Any]] = []
    for pkg in pilots.published():
        for rec in pkg.evidence.values():
            docs.append(
                {
                    "doc_id": rec.evidence_id,
                    "kind": f"evidence:{rec.kind.value}",
                    "pilot_id": pkg.pilot_id,
                    "title": rec.source_title,
                    "body": _record_text(rec),
                    "source_url": rec.source_url,
                }
            )
        for inst in pkg.instances.values():
            docs.append(
                {
                    "doc_id": f"instance:{inst.instance_id}",
                    "kind": "action_catalog",
                    "pilot_id": pkg.pilot_id,
                    "title": f"{inst.category.value} {inst.instance_id}",
                    "body": f"{inst.category.value} action {inst.instance_id} type {inst.type_id} targets "
                    f"{' '.join(inst.target_ids)} capex {inst.capex_pkr} PKR seasonal opex "
                    f"{inst.seasonal_opex_pkr} PKR lead time {inst.lead_time_days} days",
                    "source_url": None,
                }
            )
    for m in METHODOLOGY:
        docs.append(
            {
                "doc_id": m["id"],
                "kind": "methodology",
                "pilot_id": None,
                "title": m["title"],
                "body": f"{m['body']} (section {m['section']})",
                "source_url": None,
            }
        )
    for d in REGISTRY.values():
        docs.append(
            {
                "doc_id": f"metric:{d.metric_id}",
                "kind": "metric_definition",
                "pilot_id": None,
                "title": d.label,
                "body": f"{d.label}. {d.formula}. Unit {d.unit}. Boundary {d.boundary}. "
                f"Aggregation {d.aggregation}. Missing data: {d.missing}.",
                "source_url": None,
            }
        )
    return docs


def ensure_index(conn: sqlite3.Connection, pilots: PilotRepository) -> str:
    docs = corpus(pilots)
    h = content_hash(docs)
    row = conn.execute("SELECT value FROM meta WHERE key = 'evidence_corpus_hash'").fetchone()
    if row and row[0] == h:
        return h
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM evidence_fts")
        conn.executemany(
            "INSERT INTO evidence_fts (doc_id, kind, pilot_id, title, body, source_url) VALUES (?,?,?,?,?,?)",
            [
                (d["doc_id"], d["kind"], d["pilot_id"], d["title"], d["body"], d["source_url"])
                for d in docs
            ],
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('evidence_corpus_hash', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (h,),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return h


_TOKEN = re.compile(r"[\w\-]+", re.UNICODE)


def fts_query(text: str) -> str | None:
    """Turn free text into a safe FTS5 query: quoted tokens joined by OR, prefix on last."""
    toks = [t for t in _TOKEN.findall(text or "") if t.strip("-")]
    if not toks:
        return None
    toks = toks[:12]
    quoted = ['"' + t.replace('"', "") + '"' for t in toks]
    quoted[-1] = quoted[-1] + "*"
    return " OR ".join(quoted)


def search(
    conn: sqlite3.Connection,
    q: str,
    *,
    pilot_id: str | None = None,
    kind: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    query = fts_query(q)
    if query is None:
        return []
    limit = max(1, min(int(limit), MAX_RESULTS))
    sql = (
        "SELECT doc_id, kind, pilot_id, title, source_url, "
        f"snippet(evidence_fts, 4, '[', ']', ' ... ', {SNIPPET_TOKENS}) AS snippet, bm25(evidence_fts) AS score "
        "FROM evidence_fts WHERE evidence_fts MATCH ?"
    )
    args: list[Any] = [query]
    if pilot_id:
        sql += " AND (pilot_id = ? OR pilot_id IS NULL)"
        args.append(pilot_id)
    if kind:
        sql += " AND kind LIKE ?"
        args.append(kind + "%")
    sql += " ORDER BY score LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    return [
        {
            "doc_id": r["doc_id"],
            "kind": r["kind"],
            "pilot_id": r["pilot_id"],
            "title": r["title"],
            "snippet": r["snippet"],
            "source_url": r["source_url"],
            "score": float(r["score"]),
        }
        for r in rows
    ]
