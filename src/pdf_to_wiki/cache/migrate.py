"""Migrate old source_id-keyed artifact layout to hash-addressed layout.

Moves artifacts from the legacy flat layout:
    data/artifacts/{source_id}/
to the new hash-addressed layout:
    {cache_dir}/artifacts/{sha256[:2]}/{sha256}/

Also moves the SQLite cache DB from data/cache/cache.db to the
global cache directory ({cache_dir}/cache.db).

Usage:
    pdf-to-wiki migrate-cache [--old-cache-dir DIR] [--dry-run]

The old cache directory defaults to ./data/ (relative to cwd).
The new cache directory is resolved via platformdirs (typically
~/.cache/pdf-to-wiki/) or the PDF_TO_WIKI_CACHE_DIR env var.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.logging import get_logger

logger = get_logger(__name__)


def migrate_cache(
    config: WikiConfig,
    old_cache_dir: str | Path = "./data",
    dry_run: bool = False,
) -> dict[str, int]:
    """Migrate old source_id-keyed artifacts to hash-addressed layout.

    Reads source_id -> sha256 mappings from the old SQLite DB, then
    copies each artifact file from data/artifacts/{source_id}/ to
    {cache_dir}/artifacts/{sha256[:2]}/{sha256}/.

    Also copies the old cache DB to the new location.

    Args:
        config: Pipeline configuration (provides resolved paths).
        old_cache_dir: Root of the old cache directory (contains
            cache/cache.db and artifacts/).
        dry_run: If True, report what would be done but don't copy files.

    Returns:
        Dict with counts: files_moved, dirs_moved, db_moved, skipped, errors.
    """
    old_root = Path(old_cache_dir).resolve()
    old_db_path = old_root / "cache" / "cache.db"
    old_artifacts_dir = old_root / "artifacts"
    new_artifacts_dir = config.resolved_artifact_dir()
    new_db_path = config.resolved_cache_db_path()

    stats = {
        "files_moved": 0,
        "dirs_moved": 0,
        "db_moved": 0,
        "skipped": 0,
        "errors": 0,
    }

    # 1. Migrate the SQLite DB
    if old_db_path.exists():
        new_db_path.parent.mkdir(parents=True, exist_ok=True)
        if new_db_path.exists():
            logger.info(f"New DB already exists at {new_db_path}, skipping DB migration")
            stats["skipped"] += 1
        else:
            logger.info(f"Copying DB: {old_db_path} -> {new_db_path}")
            if not dry_run:
                shutil.copy2(old_db_path, new_db_path)
                stats["db_moved"] += 1
    else:
        logger.warning(f"Old DB not found at {old_db_path}")

    # 2. Read source_id -> sha256 mappings
    # Try the new DB first (may have been copied above), then the old DB
    db_path = new_db_path if new_db_path.exists() else old_db_path
    if not db_path.exists():
        logger.error("No cache DB found — cannot resolve source_id -> sha256 mappings")
        stats["errors"] += 1
        return stats

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT source_id, sha256 FROM pdf_sources").fetchall()
    conn.close()

    source_to_hash: dict[str, str] = {row[0]: row[1] for row in rows}
    logger.info(f"Found {len(source_to_hash)} registered sources in DB")

    # 3. Migrate artifact files
    if not old_artifacts_dir.exists():
        logger.warning(f"Old artifacts directory not found at {old_artifacts_dir}")
        return stats

    for source_id, sha256 in source_to_hash.items():
        old_dir = old_artifacts_dir / source_id
        if not old_dir.exists():
            logger.warning(f"No artifact directory for {source_id}")
            continue

        # New hash-addressed directory
        prefix = sha256[:2]
        new_dir = new_artifacts_dir / prefix / sha256

        # Check if already migrated
        if new_dir.exists() and any(new_dir.iterdir()):
            logger.info(f"Already migrated: {source_id} -> {sha256[:12]}...")
            stats["skipped"] += 1
            continue

        logger.info(f"Migrating {source_id} -> {sha256[:12]}... ({len(list(old_dir.iterdir()))} files)")
        if not dry_run:
            new_dir.mkdir(parents=True, exist_ok=True)
            stats["dirs_moved"] += 1

        for old_file in old_dir.iterdir():
            new_file = new_dir / old_file.name
            if new_file.exists():
                logger.debug(f"  Skipping (exists): {new_file.name}")
                stats["skipped"] += 1
                continue

            if not dry_run:
                shutil.copy2(old_file, new_file)
                stats["files_moved"] += 1
                logger.debug(f"  Copied: {old_file.name}")

        # Also save emit_manifest by source_id (flat) for stale-file cleanup
        emit_manifest = old_dir / "emit_manifest.json"
        if emit_manifest.exists() and not dry_run:
            src_alias_dir = new_artifacts_dir / source_id
            src_alias_dir.mkdir(parents=True, exist_ok=True)
            alias_file = src_alias_dir / "emit_manifest.json"
            if not alias_file.exists():
                shutil.copy2(emit_manifest, alias_file)

    return stats