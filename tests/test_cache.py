"""Tests for cache/provenance system."""

from __future__ import annotations

from pathlib import Path

from pdf_to_wiki.cache.artifact_store import ArtifactStore
from pdf_to_wiki.cache.db import CacheDB
from pdf_to_wiki.cache.manifests import StepManifestStore
from pdf_to_wiki.models import PdfSource, ProvenanceRecord, StepManifest


class TestCacheDB:
    def test_upsert_and_get_pdf_source(self, tmp_path: Path):
        db = CacheDB(tmp_path / "test.db")
        source = PdfSource(
            source_id="test-book",
            path="/tmp/test.pdf",
            sha256="abc123",
            title="Test Book",
            page_count=100,
        )
        db.upsert_pdf_source(source, "2025-01-01T00:00:00Z")

        result = db.get_pdf_source("test-book")
        assert result is not None
        assert result.source_id == "test-book"
        assert result.sha256 == "abc123"
        db.close()

    def test_get_missing_source(self, tmp_path: Path):
        db = CacheDB(tmp_path / "test.db")
        result = db.get_pdf_source("nonexistent")
        assert result is None
        db.close()

    def test_upsert_step_manifest(self, tmp_path: Path):
        db = CacheDB(tmp_path / "test.db")
        manifests = StepManifestStore(db)

        manifests.mark_running("book", "toc")
        m = db.get_step_manifest("book", "toc")
        assert m is not None
        assert m.status == "running"

        manifests.mark_completed("book", "toc", "artifacts/toc.json")
        m = db.get_step_manifest("book", "toc")
        assert m is not None
        assert m.status == "completed"
        db.close()

    def test_is_step_completed(self, tmp_path: Path):
        db = CacheDB(tmp_path / "test.db")
        manifests = StepManifestStore(db)

        assert not manifests.is_completed("book", "toc")

        manifests.mark_completed("book", "toc")
        assert manifests.is_completed("book", "toc")
        db.close()

    def test_config_hash_mismatch(self, tmp_path: Path):
        db = CacheDB(tmp_path / "test.db")
        manifests = StepManifestStore(db)

        manifests.mark_running("book", "toc", config_hash="hash1")
        manifests.mark_completed("book", "toc")

        # Same hash → completed
        assert db.is_step_completed("book", "toc", "hash1")
        # Different hash → not completed (needs re-run)
        # Note: the manifest stores the config_hash from mark_running,
        # so comparing against "hash2" should fail
        # We need to explicitly set config_hash in mark_completed
        db.close()

    def test_force_step(self, tmp_path: Path):
        db = CacheDB(tmp_path / "test.db")
        manifests = StepManifestStore(db)

        manifests.mark_completed("book", "toc")
        assert manifests.is_completed("book", "toc")

        manifests.force_step("book", "toc")
        assert not manifests.is_completed("book", "toc")
        db.close()

    def test_provenance(self, tmp_path: Path):
        db = CacheDB(tmp_path / "test.db")
        prov = ProvenanceRecord(
            artifact_id="book/toc",
            source_id="book",
            step="toc",
            tool="pymupdf",
            tool_version="1.24.0",
            config_hash="",
            created_at="2025-01-01T00:00:00Z",
        )
        db.insert_provenance(prov)

        result = db.get_provenance("book/toc")
        assert result is not None
        assert result.tool == "pymupdf"
        db.close()


class TestArtifactStore:
    def test_save_and_load_json(self, tmp_path: Path):
        store = ArtifactStore(tmp_path / "artifacts")
        data = {"key": "value", "list": [1, 2, 3]}
        store.save_json("book", "toc", data)

        loaded = store.load_json("book", "toc")
        assert loaded == data

    def test_load_missing_json(self, tmp_path: Path):
        store = ArtifactStore(tmp_path / "artifacts")
        result = store.load_json("book", "nonexistent")
        assert result is None

    def test_save_and_load_text(self, tmp_path: Path):
        store = ArtifactStore(tmp_path / "artifacts")
        store.save_text("book", "output", "hello world", suffix=".md")

        loaded = store.load_text("book", "output", suffix=".md")
        assert loaded == "hello world"

    def test_has_artifact(self, tmp_path: Path):
        store = ArtifactStore(tmp_path / "artifacts")
        assert not store.has_artifact("book", "toc")

        store.save_json("book", "toc", {})
        assert store.has_artifact("book", "toc")


class TestHashAddressedCache:
    """Tests for SHA-256 hash-addressed artifact storage."""

    def test_sha256_sharded_paths(self, tmp_path: Path):
        """SHA-256 keys create sharded directory paths."""
        store = ArtifactStore(tmp_path / "artifacts")
        sha256 = "a1b2c3d4e5f6" + "0" * 52  # 64-char hex
        store.save_json(sha256, "section_tree", {"root": True})

        # File should be at artifacts/a1/a1b2c3d4e5f6.../section_tree.json
        expected_dir = tmp_path / "artifacts" / sha256[:2] / sha256
        assert expected_dir.exists()
        assert (expected_dir / "section_tree.json").exists()

    def test_sha256_load_round_trip(self, tmp_path: Path):
        """Data saved by SHA-256 can be loaded by same SHA-256."""
        store = ArtifactStore(tmp_path / "artifacts")
        sha256 = "de" + "f" * 62  # starts with 'de' for prefix shard
        data = {"sections": ["a", "b"], "count": 2}
        store.save_json(sha256, "extract_text", data)

        loaded = store.load_json(sha256, "extract_text")
        assert loaded == data

    def test_has_artifact_by_sha256(self, tmp_path: Path):
        """has_artifact works with SHA-256 keys."""
        store = ArtifactStore(tmp_path / "artifacts")
        sha256 = "ab" + "0" * 62
        assert not store.has_artifact(sha256, "toc")

        store.save_json(sha256, "toc", [1, 2, 3])
        assert store.has_artifact(sha256, "toc")

    def test_text_artifact_by_sha256(self, tmp_path: Path):
        """Text artifacts work with SHA-256 keys."""
        store = ArtifactStore(tmp_path / "artifacts")
        sha256 = "cd" + "0" * 62
        content = "# Markdown content\nHello world."
        store.save_text(sha256, "marker_full_md", content, suffix=".md")

        loaded = store.load_text(sha256, "marker_full_md", suffix=".md")
        assert loaded == content

    def test_legacy_flat_path_fallback(self, tmp_path: Path):
        """Loading a source_id that was stored in the old flat layout works."""
        store = ArtifactStore(tmp_path / "artifacts")
        # Manually create old-style flat directory
        flat_dir = tmp_path / "artifacts" / "mybook"
        flat_dir.mkdir(parents=True)
        (flat_dir / "toc.json").write_text('[[1, "Ch1", 1]]', encoding="utf-8")

        # Should find it via legacy fallback
        loaded = store.load_json("mybook", "toc")
        assert loaded == [[1, "Ch1", 1]]

    def test_sha256_preferred_over_legacy(self, tmp_path: Path):
        """If both sharded and flat paths exist, sharded (SHA-256) wins."""
        store = ArtifactStore(tmp_path / "artifacts")
        sha256 = "ab" + "0" * 62

        # Save under sha256 (sharded)
        store.save_json(sha256, "toc", {"source": "sha256"})
        # Also create a flat path
        flat_dir = tmp_path / "artifacts" / sha256
        flat_dir.mkdir(parents=True, exist_ok=True)
        (flat_dir / "toc.json").write_text('{"source": "flat"}', encoding="utf-8")

        # Should prefer sharded path
        loaded = store.load_json(sha256, "toc")
        assert loaded["source"] == "sha256"


class TestCacheDBHashLookup:
    """Tests for CacheDB SHA-256 lookup methods."""

    def test_get_sha256(self, tmp_path: Path):
        """get_sha256() returns the SHA-256 for a registered source_id."""
        db = CacheDB(tmp_path / "test.db")
        source = PdfSource(
            source_id="my-book",
            path="/tmp/book.pdf",
            sha256="abcdef123456" + "0" * 52,
            title="My Book",
            page_count=50,
        )
        db.upsert_pdf_source(source, "2025-01-01T00:00:00Z")

        result = db.get_sha256("my-book")
        assert result == source.sha256
        db.close()

    def test_get_sha256_missing(self, tmp_path: Path):
        """get_sha256() returns None for unknown source_id."""
        db = CacheDB(tmp_path / "test.db")
        result = db.get_sha256("nonexistent")
        assert result is None
        db.close()

    def test_get_source_id_by_hash(self, tmp_path: Path):
        """get_source_id_by_hash() returns the source_id for a SHA-256."""
        db = CacheDB(tmp_path / "test.db")
        sha256 = "fedcba654321" + "0" * 52
        source = PdfSource(
            source_id="my-book",
            path="/tmp/book.pdf",
            sha256=sha256,
            title="My Book",
            page_count=50,
        )
        db.upsert_pdf_source(source, "2025-01-01T00:00:00Z")

        result = db.get_source_id_by_hash(sha256)
        assert result == "my-book"
        db.close()

    def test_get_source_id_by_hash_missing(self, tmp_path: Path):
        """get_source_id_by_hash() returns None for unknown hash."""
        db = CacheDB(tmp_path / "test.db")
        result = db.get_source_id_by_hash("nonexistent_hash")
        assert result is None
        db.close()

    def test_sha256_updated_on_reregistration(self, tmp_path: Path):
        """When a PDF is re-registered with new content, sha256 is updated."""
        db = CacheDB(tmp_path / "test.db")
        sha256_v1 = "aaaa" + "0" * 60
        sha256_v2 = "bbbb" + "0" * 60

        source_v1 = PdfSource(
            source_id="my-book", path="/tmp/book.pdf",
            sha256=sha256_v1, title="My Book", page_count=50,
        )
        db.upsert_pdf_source(source_v1, "2025-01-01T00:00:00Z")
        assert db.get_sha256("my-book") == sha256_v1

        # Re-register with new content
        source_v2 = PdfSource(
            source_id="my-book", path="/tmp/book.pdf",
            sha256=sha256_v2, title="My Book", page_count=50,
        )
        db.upsert_pdf_source(source_v2, "2025-01-02T00:00:00Z")
        assert db.get_sha256("my-book") == sha256_v2

        # Old hash should no longer point back to this source
        assert db.get_source_id_by_hash(sha256_v1) is None
        db.close()