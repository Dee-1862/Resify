"""
CiteSafe Cache Layer
====================
SQLite-based caching with three layers matching the I/O contract:

  cache.get_source(paper_id) / cache.set_source(paper_id, data)
  cache.get_verification(claim, source_id) / cache.set_verification(claim, source_id, result)
  cache.get_analysis(paper_hash) / cache.set_analysis(paper_hash, result)

Uses WAL mode for concurrent reads. Numpy embedding storage as BLOB.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from typing import Optional

import numpy as np

from server.config import settings

logger = logging.getLogger("citesafe.cache")


class CiteSafeCache:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or settings.CACHE_DB_PATH
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()
        self._stats = {"hits": 0, "misses": 0}

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                paper_id   TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                embedding  BLOB,
                fetched_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS verifications (
                claim_hash  TEXT PRIMARY KEY,
                result      TEXT NOT NULL,
                verified_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS papers (
                paper_hash  TEXT PRIMARY KEY,
                analysis    TEXT NOT NULL,
                analyzed_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sources_fetched
                ON sources(fetched_at);
            CREATE INDEX IF NOT EXISTS idx_verifications_verified
                ON verifications(verified_at);
        """)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Layer 1: Source Cache (contract: get_source / set_source)
    # ------------------------------------------------------------------

    def get_source(self, paper_id: str) -> Optional[dict]:
        """Get cached source metadata + embedding, or None."""
        row = self.conn.execute(
            "SELECT data, embedding, fetched_at FROM sources WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()

        if not row:
            self._stats["misses"] += 1
            return None

        # TTL check
        if time.time() - row[2] > settings.SOURCE_CACHE_TTL_DAYS * 86400:
            self.conn.execute("DELETE FROM sources WHERE paper_id = ?", (paper_id,))
            self.conn.commit()
            self._stats["misses"] += 1
            return None

        self._stats["hits"] += 1
        data = json.loads(row[0])
        if row[1]:
            data["embedding"] = np.frombuffer(row[1], dtype=np.float32)
        return data

    def set_source(self, paper_id: str, data: dict, embedding: Optional[np.ndarray] = None):
        """Cache source metadata and optional embedding."""
        store_data = {k: v for k, v in data.items() if k != "embedding"}
        emb_blob = embedding.astype(np.float32).tobytes() if embedding is not None else None

        self.conn.execute(
            "INSERT OR REPLACE INTO sources (paper_id, data, embedding, fetched_at) "
            "VALUES (?, ?, ?, ?)",
            (paper_id, json.dumps(store_data), emb_blob, time.time()),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Layer 2: Verification Cache (contract: get_verification / set_verification)
    # ------------------------------------------------------------------

    @staticmethod
    def _claim_hash(claim: str, source_id: str) -> str:
        return hashlib.sha256(f"{claim}|{source_id}".encode()).hexdigest()[:32]

    def get_verification(self, claim: str, source_id: str) -> Optional[dict]:
        """Get cached verification result, or None."""
        h = self._claim_hash(claim, source_id)
        row = self.conn.execute(
            "SELECT result, verified_at FROM verifications WHERE claim_hash = ?",
            (h,),
        ).fetchone()

        if not row:
            self._stats["misses"] += 1
            return None

        if time.time() - row[1] > settings.VERIFICATION_CACHE_TTL_DAYS * 86400:
            self.conn.execute("DELETE FROM verifications WHERE claim_hash = ?", (h,))
            self.conn.commit()
            self._stats["misses"] += 1
            return None

        self._stats["hits"] += 1
        return json.loads(row[0])

    def set_verification(self, claim: str, source_id: str, result: dict):
        """Cache a verification result."""
        h = self._claim_hash(claim, source_id)
        self.conn.execute(
            "INSERT OR REPLACE INTO verifications (claim_hash, result, verified_at) "
            "VALUES (?, ?, ?)",
            (h, json.dumps(result), time.time()),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Layer 3: Paper Analysis Cache (contract: get_analysis / set_analysis)
    # ------------------------------------------------------------------

    @staticmethod
    def _paper_hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:32]

    def get_analysis(self, paper_hash: str) -> Optional[dict]:
        """Get cached full-paper analysis, or None."""
        row = self.conn.execute(
            "SELECT analysis, analyzed_at FROM papers WHERE paper_hash = ?",
            (paper_hash,),
        ).fetchone()

        if not row:
            self._stats["misses"] += 1
            return None

        if time.time() - row[1] > settings.PAPER_CACHE_TTL_HOURS * 3600:
            self.conn.execute("DELETE FROM papers WHERE paper_hash = ?", (paper_hash,))
            self.conn.commit()
            self._stats["misses"] += 1
            return None

        self._stats["hits"] += 1
        return json.loads(row[0])

    def set_analysis(self, paper_hash: str, result: dict):
        """Cache a full paper analysis."""
        self.conn.execute(
            "INSERT OR REPLACE INTO papers (paper_hash, analysis, analyzed_at) "
            "VALUES (?, ?, ?)",
            (paper_hash, json.dumps(result), time.time()),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def hash_paper(self, text: str) -> str:
        """Public helper for generating paper hashes."""
        return self._paper_hash(text)

    def get_stats(self) -> dict:
        counts = {}
        for table in ("sources", "verifications", "papers"):
            row = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = row[0] if row else 0
        total = self._stats["hits"] + self._stats["misses"]
        return {
            "tables": counts,
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "hit_rate": round(self._stats["hits"] / max(1, total) * 100, 1),
        }

    def cleanup_expired(self):
        now = time.time()
        self.conn.execute(
            "DELETE FROM sources WHERE ? - fetched_at > ?",
            (now, settings.SOURCE_CACHE_TTL_DAYS * 86400),
        )
        self.conn.execute(
            "DELETE FROM verifications WHERE ? - verified_at > ?",
            (now, settings.VERIFICATION_CACHE_TTL_DAYS * 86400),
        )
        self.conn.execute(
            "DELETE FROM papers WHERE ? - analyzed_at > ?",
            (now, settings.PAPER_CACHE_TTL_HOURS * 3600),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
