"""Filesystem artifact store for intermediate pipeline artifacts.

Stores JSON, Markdown, and other file artifacts under a structured
directory layout so they can be inspected and reused across runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pdf_to_wiki.logging import get_logger

logger = get_logger(__name__)


class ArtifactStore:
    """Manages persisted intermediate artifacts on disk."""

    def __init__(self, artifact_dir: str | Path) -> None:
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def _source_dir(self, source_id: str) -> Path:
        d = self.artifact_dir / source_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_json(self, source_id: str, name: str, data: Any) -> Path:
        """Save a JSON artifact and return its path."""
        d = self._source_dir(source_id)
        path = d / f"{name}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Artifact saved: {path}")
        return path

    def load_json(self, source_id: str, name: str) -> Any | None:
        """Load a JSON artifact, returning None if not found."""
        path = self.artifact_dir / source_id / f"{name}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_text(self, source_id: str, name: str, content: str, suffix: str = ".txt") -> Path:
        """Save a text artifact and return its path."""
        d = self._source_dir(source_id)
        path = d / f"{name}{suffix}"
        path.write_text(content, encoding="utf-8")
        logger.info(f"Artifact saved: {path}")
        return path

    def load_text(self, source_id: str, name: str, suffix: str = ".txt") -> str | None:
        """Load a text artifact, returning None if not found."""
        path = self.artifact_dir / source_id / f"{name}{suffix}"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def has_artifact(self, source_id: str, name: str, suffix: str = ".json") -> bool:
        """Check if an artifact exists."""
        path = self.artifact_dir / source_id / f"{name}{suffix}"
        return path.exists()

    def artifact_path(self, source_id: str, name: str, suffix: str = ".json") -> Path:
        """Return the path where an artifact would be stored, without writing."""
        return self.artifact_dir / source_id / f"{name}{suffix}"