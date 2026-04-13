"""Step manifest tracking — high-level cache check and update operations."""

from __future__ import annotations

from datetime import datetime, timezone

from rulebook_wiki.cache.db import CacheDB
from rulebook_wiki.logging import get_logger
from rulebook_wiki.models import StepManifest

logger = get_logger(__name__)


class StepManifestStore:
    """Manages pipeline step completion tracking via the cache DB."""

    def __init__(self, db: CacheDB) -> None:
        self.db = db

    def is_completed(self, source_id: str, step: str, config_hash: str = "") -> bool:
        """Check if a step has been completed (with same config hash if specified)."""
        return self.db.is_step_completed(source_id, step, config_hash)

    def mark_running(self, source_id: str, step: str, config_hash: str = "") -> None:
        now = _now_iso()
        m = self.db.get_step_manifest(source_id, step) or StepManifest(
            source_id=source_id, step=step, status="running", config_hash=config_hash
        )
        m.status = "running"
        m.started_at = now
        m.config_hash = config_hash
        self.db.upsert_step_manifest(m)
        logger.info(f"Step {step} for {source_id} → running")

    def mark_completed(self, source_id: str, step: str, artifact_path: str | None = None) -> None:
        now = _now_iso()
        m = self.db.get_step_manifest(source_id, step)
        if m is None:
            m = StepManifest(source_id=source_id, step=step, status="completed")
        m.status = "completed"
        m.completed_at = now
        if artifact_path is not None:
            m.artifact_path = artifact_path
        self.db.upsert_step_manifest(m)
        logger.info(f"Step {step} for {source_id} → completed")

    def mark_failed(self, source_id: str, step: str) -> None:
        now = _now_iso()
        m = self.db.get_step_manifest(source_id, step)
        if m is None:
            m = StepManifest(source_id=source_id, step=step, status="running")
        m.status = "failed"
        m.completed_at = now
        self.db.upsert_step_manifest(m)
        logger.error(f"Step {step} for {source_id} → failed")

    def force_step(self, source_id: str, step: str) -> None:
        """Reset step so it will be re-run."""
        self.db.force_step(source_id, step)
        logger.info(f"Step {step} for {source_id} → forced (will re-run)")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()