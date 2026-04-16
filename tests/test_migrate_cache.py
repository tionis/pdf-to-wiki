"""Tests for cache migration from source_id layout to hash-addressed layout."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pdf_to_wiki.cache.migrate import migrate_cache
from pdf_to_wiki.config import WikiConfig


def _create_old_layout(
    old_root: Path,
    sources: dict[str, str],
    artifacts: dict[str, dict[str, str]],
) -> None:
    """Set up an old-style cache directory.

    Args:
        old_root: Root directory (contains cache/ and artifacts/).
        sources: {source_id: sha256} mappings to put in the DB.
        artifacts: {source_id: {filename: content}} artifact files.
    """
    # Create DB
    db_dir = old_root / "cache"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "cache.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pdf_sources (
            source_id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            title TEXT,
            page_count INTEGER NOT NULL,
            registered_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS step_manifests (
            source_id TEXT NOT NULL,
            step TEXT NOT NULL,
            status TEXT NOT NULL,
            artifact_path TEXT,
            config_hash TEXT,
            started_at TEXT,
            completed_at TEXT,
            PRIMARY KEY (source_id, step)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS provenance (
            artifact_id TEXT PRIMARY KEY,
            source_id TEXT,
            step TEXT,
            tool TEXT,
            tool_version TEXT,
            config_hash TEXT,
            created_at TEXT
        )
    """)
    for source_id, sha256 in sources.items():
        conn.execute(
            "INSERT INTO pdf_sources VALUES (?, ?, ?, ?, ?, ?)",
            (source_id, f"/tmp/{source_id}.pdf", sha256, "Test Book", 100,
             "2025-01-01T00:00:00Z"),
        )
    conn.commit()
    conn.close()

    # Create artifact files
    artifacts_dir = old_root / "artifacts"
    for source_id, files in artifacts.items():
        src_dir = artifacts_dir / source_id
        src_dir.mkdir(parents=True)
        for filename, content in files.items():
            (src_dir / filename).write_text(content, encoding="utf-8")


class TestMigrateCache:
    def test_migrate_moves_files_to_hash_addressed_dirs(self, tmp_path: Path):
        """Artifact files are moved to {sha256[:2]}/{sha256}/ layout."""
        old_root = tmp_path / "old"
        sha256 = "ab1234567890" + "0" * 52  # starts with 'ab'
        _create_old_layout(
            old_root,
            sources={"my-book": sha256},
            artifacts={"my-book": {
                "toc.json": '[{"level":1,"title":"Ch1","pdf_page":0}]',
                "section_tree.json": '{"nodes":{},"root_ids":[]}',
            }},
        )

        config = WikiConfig(
            output_dir=str(tmp_path / "output"),
            cache_db_path=str(tmp_path / "new_cache" / "cache.db"),
            artifact_dir=str(tmp_path / "new_cache" / "artifacts"),
        )

        stats = migrate_cache(config, old_cache_dir=old_root)
        assert stats["dirs_moved"] == 1
        assert stats["files_moved"] == 2

        # Verify new layout
        new_dir = tmp_path / "new_cache" / "artifacts" / "ab" / sha256
        assert (new_dir / "toc.json").exists()
        assert (new_dir / "section_tree.json").exists()

    def test_migrate_copies_db(self, tmp_path: Path):
        """SQLite DB is copied to the new location."""
        old_root = tmp_path / "old"
        sha256 = "cd" + "0" * 62
        _create_old_layout(
            old_root,
            sources={"book": sha256},
            artifacts={"book": {"toc.json": "[]"}},
        )

        config = WikiConfig(
            output_dir=str(tmp_path / "output"),
            cache_db_path=str(tmp_path / "new_cache" / "cache.db"),
            artifact_dir=str(tmp_path / "new_cache" / "artifacts"),
        )

        stats = migrate_cache(config, old_cache_dir=old_root)
        assert stats["db_moved"] == 1
        assert (tmp_path / "new_cache" / "cache.db").exists()

        # Verify DB content
        conn = sqlite3.connect(str(tmp_path / "new_cache" / "cache.db"))
        rows = conn.execute("SELECT source_id, sha256 FROM pdf_sources").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == "book"

    def test_migrate_skips_already_migrated(self, tmp_path: Path):
        """Already-migrated dirs are skipped."""
        old_root = tmp_path / "old"
        sha256 = "ef" + "0" * 62
        _create_old_layout(
            old_root,
            sources={"book": sha256},
            artifacts={"book": {"toc.json": "[]"}},
        )

        config = WikiConfig(
            output_dir=str(tmp_path / "output"),
            cache_db_path=str(tmp_path / "new_cache" / "cache.db"),
            artifact_dir=str(tmp_path / "new_cache" / "artifacts"),
        )

        # First migration
        stats1 = migrate_cache(config, old_cache_dir=old_root)
        assert stats1["dirs_moved"] == 1

        # Second migration should skip
        stats2 = migrate_cache(config, old_cache_dir=old_root)
        assert stats2["skipped"] >= 1
        assert stats2["dirs_moved"] == 0

    def test_migrate_dry_run(self, tmp_path: Path):
        """Dry run reports but doesn't copy files."""
        old_root = tmp_path / "old"
        sha256 = "aa" + "0" * 62
        _create_old_layout(
            old_root,
            sources={"book": sha256},
            artifacts={"book": {"toc.json": "[1,2,3]"}},
        )

        config = WikiConfig(
            output_dir=str(tmp_path / "output"),
            cache_db_path=str(tmp_path / "new_cache" / "cache.db"),
            artifact_dir=str(tmp_path / "new_cache" / "artifacts"),
        )

        stats = migrate_cache(config, old_cache_dir=old_root, dry_run=True)
        assert stats["dirs_moved"] == 0  # dry-run doesn't move
        assert stats["files_moved"] == 0  # dry-run doesn't copy
        assert stats["db_moved"] == 0  # dry-run doesn't copy DB

        # Verify no files were created
        new_dir = tmp_path / "new_cache" / "artifacts"
        assert not (new_dir / "aa" / sha256 / "toc.json").exists()

    def test_migrate_multiple_books(self, tmp_path: Path):
        """Multiple books are all migrated correctly."""
        old_root = tmp_path / "old"
        sha256_a = "aa" + "0" * 62
        sha256_b = "bb" + "0" * 62
        sha256_c = "12" + "0" * 62
        _create_old_layout(
            old_root,
            sources={"book-a": sha256_a, "book-b": sha256_b, "book-c": sha256_c},
            artifacts={
                "book-a": {"toc.json": "[1]", "section_tree.json": "{}"},
                "book-b": {"toc.json": "[2]"},
                "book-c": {"toc.json": "[3]", "marker_full_md.md": "# Content"},
            },
        )

        config = WikiConfig(
            output_dir=str(tmp_path / "output"),
            cache_db_path=str(tmp_path / "new_cache" / "cache.db"),
            artifact_dir=str(tmp_path / "new_cache" / "artifacts"),
        )

        stats = migrate_cache(config, old_cache_dir=old_root)
        assert stats["dirs_moved"] == 3
        assert stats["files_moved"] == 5  # 2 + 1 + 2

        # Verify each book in its correct sharded path
        assert (tmp_path / "new_cache" / "artifacts" / "aa" / sha256_a / "toc.json").exists()
        assert (tmp_path / "new_cache" / "artifacts" / "bb" / sha256_b / "toc.json").exists()
        assert (tmp_path / "new_cache" / "artifacts" / "12" / sha256_c / "toc.json").exists()

    def test_emit_manifest_also_saved_by_source_id(self, tmp_path: Path):
        """Emit manifest is also saved flat by source_id for stale-file cleanup."""
        old_root = tmp_path / "old"
        sha256 = "cc" + "0" * 62
        _create_old_layout(
            old_root,
            sources={"my-book": sha256},
            artifacts={"my-book": {
                "emit_manifest.json": '{"section-x": "books/my-book/section-x.md"}',
                "toc.json": "[]",
            }},
        )

        config = WikiConfig(
            output_dir=str(tmp_path / "output"),
            cache_db_path=str(tmp_path / "new_cache" / "cache.db"),
            artifact_dir=str(tmp_path / "new_cache" / "artifacts"),
        )

        migrate_cache(config, old_cache_dir=old_root)

        # Emit manifest should exist both by hash and by source_id
        by_hash = tmp_path / "new_cache" / "artifacts" / "cc" / sha256 / "emit_manifest.json"
        by_source_id = tmp_path / "new_cache" / "artifacts" / "my-book" / "emit_manifest.json"
        assert by_hash.exists()
        assert by_source_id.exists()

    def test_no_old_db_graceful_error(self, tmp_path: Path):
        """Graceful handling when old DB doesn't exist."""
        old_root = tmp_path / "old"
        old_root.mkdir()
        (old_root / "artifacts" / "some-book").mkdir(parents=True)
        (old_root / "artifacts" / "some-book" / "toc.json").write_text("[]")

        config = WikiConfig(
            output_dir=str(tmp_path / "output"),
            cache_db_path=str(tmp_path / "new_cache" / "cache.db"),
            artifact_dir=str(tmp_path / "new_cache" / "artifacts"),
        )

        stats = migrate_cache(config, old_cache_dir=old_root)
        assert stats["errors"] == 1