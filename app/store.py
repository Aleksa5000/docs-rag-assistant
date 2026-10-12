"""SQLite storage plus BM25 retrieval."""
import sqlite3
from contextlib import closing

from rank_bm25 import BM25Plus

from . import config
from .chunking import tokenize

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filename TEXT NOT NULL,
  stored_path TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  page INTEGER,
  idx INTEGER NOT NULL,
  text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with closing(connect()) as conn:
        conn.executescript(SCHEMA)


def add_document(filename: str, stored_path: str | None, chunks: list[tuple[int | None, str]]) -> int:
    """`chunks` is a list of (page or None, text)."""
    with closing(connect()) as conn, conn:
        doc_id = conn.execute(
            "INSERT INTO documents (filename, stored_path) VALUES (?, ?)", (filename, stored_path)
        ).lastrowid
        conn.executemany(
            "INSERT INTO chunks (doc_id, page, idx, text) VALUES (?, ?, ?, ?)",
            [(doc_id, page, i, text) for i, (page, text) in enumerate(chunks, start=1)],
        )
    return doc_id


def list_documents() -> list[dict]:
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT d.id, d.filename, d.created_at, COUNT(c.id) AS chunks "
            "FROM documents d LEFT JOIN chunks c ON c.doc_id = d.id GROUP BY d.id ORDER BY d.id"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_document(doc_id: int) -> str | None:
    """Returns the stored file path ('' if none) so the caller can unlink it, or None if unknown id."""
    with closing(connect()) as conn, conn:
        row = conn.execute("SELECT stored_path FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return row["stored_path"] or ""


def search(query: str, k: int | None = None) -> list[dict]:
    """Top-k chunks by BM25. Re-tokenizes every chunk and rebuilds the index per query.
    shortcut: every question pays a cost linear in the whole corpus; beyond a few thousand chunks cache
    the index (invalidate on upload/delete) or move to a search engine/vector DB."""
    k = config.top_k() if k is None else k
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT c.id, c.doc_id, c.page, c.idx, c.text, d.filename "
            "FROM chunks c JOIN documents d ON d.id = c.doc_id"
        ).fetchall()
    q = tokenize(query)
    if not rows or not q:
        return []
    docs = [tokenize(r["text"]) for r in rows]
    scores = BM25Plus(docs).get_scores(q)
    q_set = set(q)
    ranked = sorted(zip(scores, rows, docs, strict=True), key=lambda p: p[0], reverse=True)
    # Require at least one real term overlap, otherwise "no answer" is the honest result.
    return [{**dict(r), "score": float(s)} for s, r, d in ranked if q_set & set(d)][:k]
