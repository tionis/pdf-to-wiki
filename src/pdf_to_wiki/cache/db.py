"""SQLite-backed cache / provenance database.

Schema:
- pdf_sources: registered PDF metadata
- step_manifests: per-step completion tracking
- provenance: artifact provenance records
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pdf_to_wiki.logging import get_logger
from pdf_to_wiki.models import PdfSource, ProvenanceRecord, StepManifest

logger = get_logger(__name__)

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS pdf_sources (
    source_id   TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    title       TEXT,
    page_count  INTEGER NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS step_manifests (
    source_id   TEXT NOT NULL,
    step        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    artifact_path TEXT,
    started_at  TEXT,
    completed_at TEXT,
    config_hash TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source_id, step)
);

CREATE TABLE IF NOT EXISTS provenance (
    artifact_id   TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL,
    section_id    TEXT,
    step          TEXT NOT NULL,
    tool          TEXT NOT NULL,
    tool_version  TEXT,
    config_hash   TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
"""


class CacheDB:
    """SQLite cache / provenance store."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._init_schema(self._conn)
        return self._conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(_SCHEMA_V1)
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- PDF source operations --

    def upsert_pdf_source(self, src: PdfSource, registered_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO pdf_sources (source_id, path, sha256, title, page_count, registered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                path=excluded.path,
                sha256=excluded.sha256,
                title=excluded.title,
                page_count=excluded.page_count,
                registered_at=excluded.registered_at
            """,
            (src.source_id, src.path, src.sha256, src.title, src.page_count, registered_at),
        )
        self.conn.commit()

    def get_pdf_source(self, source_id: str) -> PdfSource | None:
        row = self.conn.execute(
            "SELECT source_id, path, sha256, title, page_count FROM pdf_sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row is None:
            return None
        return PdfSource(
            source_id=row["source_id"],
            path=row["path"],
            sha256=row["sha256"],
            title=row["title"],
            page_count=row["page_count"],
        )

    def list_pdf_sources(self) -> list[PdfSource]:
        rows = self.conn.execute(
            "SELECT source_id, path, sha256, title, page_count FROM pdf_sources ORDER BY source_id"
        ).fetchall()
        return [
            PdfSource(
                source_id=r["source_id"],
                path=r["path"],
                sha256=r["sha256"],
                title=r["title"],
                page_count=r["page_count"],
            )
            for r in rows
        ]

    def get_sha256(self, source_id: str) -> str | None:
        """Look up the SHA-256 hash for a source_id."""
        row = self.conn.execute(
            "SELECT sha256 FROM pdf_sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        return row["sha256"] if row else None

    def get_source_id_by_hash(self, sha256: str) -> str | None:
        """Look up the source_id for a SHA-256 hash."""
        row = self.conn.execute(
            "SELECT source_id FROM pdf_sources WHERE sha256 = ?",
            (sha256,),
        ).fetchone()
        return row["source_id"] if row else None

    # -- Step manifest operations --

    def get_step_manifest(self, source_id: str, step: str) -> StepManifest | None:
        row = self.conn.execute(
            """
            SELECT source_id, step, status, artifact_path, started_at, completed_at, config_hash
            FROM step_manifests WHERE source_id = ? AND step = ?
            """,
            (source_id, step),
        ).fetchone()
        if row is None:
            return None
        return StepManifest(
            source_id=row["source_id"],
            step=row["step"],
            status=row["status"],
            artifact_path=row["artifact_path"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            config_hash=row["config_hash"],
        )

    def upsert_step_manifest(self, manifest: StepManifest) -> None:
        self.conn.execute(
            """
            INSERT INTO step_manifests (source_id, step, status, artifact_path, started_at, completed_at, config_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, step) DO UPDATE SET
                status=excluded.status,
                artifact_path=excluded.artifact_path,
                started_at=excluded.started_at,
                completed_at=excluded.completed_at,
                config_hash=excluded.config_hash
            """,
            (
                manifest.source_id,
                manifest.step,
                manifest.status,
                manifest.artifact_path,
                manifest.started_at,
                manifest.completed_at,
                manifest.config_hash,
            ),
        )
        self.conn.commit()

    def is_step_completed(self, source_id: str, step: str, config_hash: str = "") -> bool:
        """Check if a step is completed with the same config hash."""
        m = self.get_step_manifest(source_id, step)
        if m is None or m.status != "completed":
            return False
        if config_hash and m.config_hash and m.config_hash != config_hash:
            return False
        return True

    def force_step(self, source_id: str, step: str) -> None:
        """Reset a step to pending so it will be re-run."""
        self.conn.execute(
            "UPDATE step_manifests SET status = 'pending' WHERE source_id = ? AND step = ?",
            (source_id, step),
        )
        self.conn.commit()

    # -- Provenance operations --

    def insert_provenance(self, record: ProvenanceRecord) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO provenance
            (artifact_id, source_id, section_id, step, tool, tool_version, config_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.artifact_id,
                record.source_id,
                record.section_id,
                record.step,
                record.tool,
                record.tool_version,
                record.config_hash,
                record.created_at,
            ),
        )
        self.conn.commit()

    def get_provenance(self, artifact_id: str) -> ProvenanceRecord | None:
        row = self.conn.execute(
            """
            SELECT artifact_id, source_id, section_id, step, tool, tool_version, config_hash, created_at
            FROM provenance WHERE artifact_id = ?
            """,
            (artifact_id,),
        ).fetchone()
        if row is None:
            return None
        return ProvenanceRecord(**dict(row))