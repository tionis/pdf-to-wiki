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
    """Manages persisted intermediate artifacts on disk.

    Artifacts are stored in a content-addressed layout using the PDF's
    SHA-256 hash as the directory key, with 2-character prefix sharding
    to avoid thousands of subdirectories:

        artifacts/ac/ac899aafe4fe.../marker_full_md.md
        artifacts/ac/ac899aafe4fe.../section_tree.json

    The public API uses `content_key` as the identifier — callers should
    pass the PDF's SHA-256 hash. For convenience, source_id strings
    are also accepted and stored transparently.
    """

    def __init__(self, artifact_dir: str | Path) -> None:
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def _key_dir(self, content_key: str) -> Path:
        """Return the directory path for a content key.

        Uses 2-character prefix sharding:
          content_key = 'ac899aafe4fe...' → artifacts/ac/ac899aafe4fe.../
        """
        prefix = content_key[:2]
        d = self.artifact_dir / prefix / content_key
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_json(self, content_key: str, name: str, data: Any) -> Path:
        """Save a JSON artifact and return its path."""
        d = self._key_dir(content_key)
        path = d / f"{name}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Artifact saved: {path}")
        return path

    def load_json(self, content_key: str, name: str) -> Any | None:
        """Load a JSON artifact, returning None if not found."""
        path = self.artifact_dir / content_key[:2] / content_key / f"{name}.json"
        if not path.exists():
            # Legacy fallback: try old flat path (artifacts/{source_id}/{name}.json)
            path = self.artifact_dir / content_key / f"{name}.json"
            if not path.exists():
                return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_text(self, content_key: str, name: str, content: str, suffix: str = ".txt") -> Path:
        """Save a text artifact and return its path."""
        d = self._key_dir(content_key)
        path = d / f"{name}{suffix}"
        path.write_text(content, encoding="utf-8")
        logger.info(f"Artifact saved: {path}")
        return path

    def load_text(self, content_key: str, name: str, suffix: str = ".txt") -> str | None:
        """Load a text artifact, returning None if not found."""
        path = self.artifact_dir / content_key[:2] / content_key / f"{name}{suffix}"
        if not path.exists():
            # Legacy fallback
            path = self.artifact_dir / content_key / f"{name}{suffix}"
            if not path.exists():
                return None
        return path.read_text(encoding="utf-8")

    def has_artifact(self, content_key: str, name: str, suffix: str = ".json") -> bool:
        """Check if an artifact exists."""
        path = self.artifact_dir / content_key[:2] / content_key / f"{name}{suffix}"
        if path.exists():
            return True
        # Legacy fallback
        return (self.artifact_dir / content_key / f"{name}{suffix}").exists()

    def artifact_path(self, content_key: str, name: str, suffix: str = ".json") -> Path:
        """Return the path where an artifact would be stored, without writing."""
        return self.artifact_dir / content_key[:2] / content_key / f"{name}{suffix}"