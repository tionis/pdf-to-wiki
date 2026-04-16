"""Tests for BlobForge import functionality."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import fitz
import pytest

from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.ingest.import_blobforge import import_blobforge, _read_from_zip


def _resolve_content_key(source_id: str, config: WikiConfig) -> str:
    """Resolve sha256 content key for artifact lookups in tests."""
    from pdf_to_wiki.cache.artifact_store import ArtifactStore
    from pdf_to_wiki.cache.db import CacheDB
    db = CacheDB(config.resolved_cache_db_path())
    sha256 = db.get_sha256(source_id)
    db.close()
    return sha256 or source_id


class TestReadFromZip:
    """Tests for reading content from BlobForge conversion zips."""

    def test_read_content_md(self, tmp_path: Path):
        """Read content.md and info.json from a BlobForge zip."""
        # Create a mock BlobForge zip
        content = "# Test Book\n\nSome content here."
        info = {
            "hash": "abc123",
            "original_filename": "test.pdf",
            "tags": ["rpg", "test"],
            "marker_meta": {"version": "1.0"},
        }
        zip_path = tmp_path / "abc123.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("content.md", content)
            zf.writestr("info.json", json.dumps(info))

        md_text, info_dict = _read_from_zip(str(zip_path))
        assert md_text == content
        assert info_dict["hash"] == "abc123"
        assert info_dict["original_filename"] == "test.pdf"

    def test_read_zip_without_info(self, tmp_path: Path):
        """Zip with only content.md works fine."""
        content = "# Minimal\n\nContent."
        zip_path = tmp_path / "minimal.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("content.md", content)

        md_text, info_dict = _read_from_zip(str(zip_path))
        assert md_text == content
        assert info_dict == {}

    def test_read_zip_with_assets(self, tmp_path: Path):
        """Zip with assets/ directory is readable."""
        content = "# With Assets\n\n![img](assets/test.png)"
        zip_path = tmp_path / "with_assets.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("content.md", content)
            zf.writestr("assets/test.png", b"\x89PNG\r\n")  # Minimal PNG header

        md_text, info_dict = _read_from_zip(str(zip_path))
        assert "assets/test.png" in md_text


class TestImportBlobForge:
    """Tests for the import_blobforge function."""

    def _create_test_pdf(self, path: Path, num_pages: int = 3) -> None:
        """Create a minimal test PDF."""
        doc = fitz.open()
        for i in range(num_pages):
            page = doc.new_page()
            page.insert_text(fitz.Point(50, 50), f"Page {i + 1}", fontsize=12)
        doc.save(str(path))
        doc.close()

    def _create_blobforge_zip(
        self, path: Path, content: str, info: dict | None = None
    ) -> Path:
        """Create a BlobForge-style conversion zip."""
        zip_path = path / "conversion.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("content.md", content)
            if info:
                zf.writestr("info.json", json.dumps(info))
        return zip_path

    def test_import_from_zip(self, tmp_path: Path, config: WikiConfig):
        """Import from a BlobForge zip places marker artifact correctly."""
        from pdf_to_wiki.cache.artifact_store import ArtifactStore

        # Create test PDF
        pdf_path = tmp_path / "test.pdf"
        self._create_test_pdf(pdf_path)

        # Create BlobForge zip
        content = "# Chapter 1\n\nSome marker output.\n\n# Chapter 2\n\nMore content."
        zip_path = self._create_blobforge_zip(
            tmp_path,
            content,
            info={"hash": "abc123", "original_filename": "test.pdf"},
        )

        # Import
        result = import_blobforge(
            pdf_path=str(pdf_path),
            config=config,
            zip_path=str(zip_path),
        )

        assert result["status"] == "imported"
        assert result["chars"] == len(content)
        source_id = result["source_id"]

        # Verify marker artifact was saved
        artifacts = ArtifactStore(config.resolved_artifact_dir())
        cached_md = artifacts.load_text(_resolve_content_key(source_id, config), "marker_full_md", suffix=".md")
        assert cached_md == content

        # Verify PDF is registered
        from pdf_to_wiki.cache.db import CacheDB
        db = CacheDB(config.resolved_cache_db_path())
        source = db.get_pdf_source(source_id)
        db.close()
        assert source is not None
        assert source.page_count == 3

    def test_import_from_markdown_file(self, tmp_path: Path, config: WikiConfig):
        """Import from a direct content.md file."""
        from pdf_to_wiki.cache.artifact_store import ArtifactStore

        # Create test PDF
        pdf_path = tmp_path / "test2.pdf"
        self._create_test_pdf(pdf_path)

        # Create content.md
        content = "# Title\n\nExtracted text."
        md_path = tmp_path / "content.md"
        md_path.write_text(content)

        # Import
        result = import_blobforge(
            pdf_path=str(pdf_path),
            config=config,
            markdown_path=str(md_path),
        )

        assert result["status"] == "imported"
        assert result["chars"] == len(content)

        # Verify artifact
        artifacts = ArtifactStore(config.resolved_artifact_dir())
        cached_md = artifacts.load_text(_resolve_content_key(result["source_id"], config), "marker_full_md", suffix=".md")
        assert cached_md == content

    def test_import_skip_existing(self, tmp_path: Path, config: WikiConfig):
        """Import skips if marker artifact already exists (without --force)."""
        from pdf_to_wiki.cache.artifact_store import ArtifactStore

        # Create test PDF
        pdf_path = tmp_path / "test3.pdf"
        self._create_test_pdf(pdf_path)

        # First import
        content1 = "# Version 1\n\nOriginal."
        zip1 = self._create_blobforge_zip(tmp_path, content1)
        result1 = import_blobforge(
            pdf_path=str(pdf_path),
            config=config,
            zip_path=str(zip1),
        )
        source_id = result1["source_id"]

        # Second import (without force) should skip
        content2 = "# Version 2\n\nUpdated."
        zip2 = tmp_path / "v2.zip"
        with zipfile.ZipFile(zip2, "w") as zf:
            zf.writestr("content.md", content2)

        result2 = import_blobforge(
            pdf_path=str(pdf_path),
            config=config,
            zip_path=str(zip2),
            force=False,
        )

        assert result2["status"] == "skipped_existing"

        # Original content should still be there
        artifacts = ArtifactStore(config.resolved_artifact_dir())
        cached_md = artifacts.load_text(_resolve_content_key(source_id, config), "marker_full_md", suffix=".md")
        assert cached_md == content1

    def test_import_force_overwrite(self, tmp_path: Path, config: WikiConfig):
        """Import with --force overwrites existing marker artifact."""
        from pdf_to_wiki.cache.artifact_store import ArtifactStore

        # Create test PDF
        pdf_path = tmp_path / "test4.pdf"
        self._create_test_pdf(pdf_path)

        # First import
        content1 = "# Version 1\n\nOriginal."
        zip1 = self._create_blobforge_zip(tmp_path, content1)
        import_blobforge(pdf_path=str(pdf_path), config=config, zip_path=str(zip1))
        source_id = "test4"  # predictable source_id

        # Second import with force
        content2 = "# Version 2\n\nUpdated."
        zip2 = tmp_path / "v2.zip"
        with zipfile.ZipFile(zip2, "w") as zf:
            zf.writestr("content.md", content2)

        result = import_blobforge(
            pdf_path=str(pdf_path),
            config=config,
            zip_path=str(zip2),
            force=True,
        )

        assert result["status"] == "imported"

        # New content should be there
        artifacts = ArtifactStore(config.resolved_artifact_dir())
        cached_md = artifacts.load_text(_resolve_content_key(result["source_id"], config), "marker_full_md", suffix=".md")
        assert cached_md == content2

    def test_import_requires_zip_or_markdown(self, tmp_path: Path, config: WikiConfig):
        """Import requires either --zip or --markdown."""
        pdf_path = tmp_path / "test5.pdf"
        self._create_test_pdf(pdf_path)

        with pytest.raises(ValueError, match="Must provide either"):
            import_blobforge(pdf_path=str(pdf_path), config=config)

    def test_import_saves_blobforge_info(self, tmp_path: Path, config: WikiConfig):
        """BlobForge info.json is saved as an artifact."""
        from pdf_to_wiki.cache.artifact_store import ArtifactStore

        pdf_path = tmp_path / "test6.pdf"
        self._create_test_pdf(pdf_path)

        info = {"hash": "deadbeef", "original_filename": "test.pdf", "tags": ["rpg"]}
        zip_path = self._create_blobforge_zip(tmp_path, "# Test\n\nContent.", info=info)

        result = import_blobforge(
            pdf_path=str(pdf_path),
            config=config,
            zip_path=str(zip_path),
        )

        artifacts = ArtifactStore(config.resolved_artifact_dir())
        saved_info = artifacts.load_json(_resolve_content_key(result["source_id"], config), "blobforge_info")
        assert saved_info is not None
        assert saved_info["hash"] == "deadbeef"

    def test_import_with_images(self, tmp_path: Path, config: WikiConfig):
        """BlobForge zip with images extracts them to .assets/."""
        pdf_path = tmp_path / "test7.pdf"
        self._create_test_pdf(pdf_path)

        content = "# Test\n\n![img](assets/img1.png)"
        zip_path = tmp_path / "with_images.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("content.md", content)
            zf.writestr("info.json", json.dumps({"hash": "aaa"}))
            zf.writestr("assets/img1.png", b"\x89PNG\r\n\x1a\n")
            zf.writestr("assets/img2.jpeg", b"\xff\xd8\xff\xe0")

        result = import_blobforge(
            pdf_path=str(pdf_path),
            config=config,
            zip_path=str(zip_path),
        )

        assert result["images"] == 2

        # Check files exist in .assets/
        assets_dir = (
            config.resolved_output_dir()
            / config.books_dir
            / result["source_id"]
            / ".assets"
        )
        assert assets_dir.exists()
        assert (assets_dir / "img1.png").exists()
        assert (assets_dir / "img2.jpeg").exists()

    def test_import_then_build_uses_cached_marker(self, tmp_path: Path, config: WikiConfig):
        """After import, running build uses the cached Marker output (no Marker call)."""
        from pdf_to_wiki.ingest.extract_toc import extract_toc
        from pdf_to_wiki.ingest.extract_page_labels import extract_page_labels as extract_pl
        from pdf_to_wiki.ingest.build_section_tree import build_section_tree
        from pdf_to_wiki.ingest.extract_text import extract_text

        # Create test PDF with enough content for a TOC
        doc = fitz.open()
        for i in range(5):
            page = doc.new_page()
            page.insert_text(
                fitz.Point(50, 50),
                f"Page {i + 1}\n\nContent for page {i + 1}.",
                fontsize=12,
            )
        pdf_path = tmp_path / "test_build.pdf"
        doc.save(str(pdf_path))
        doc.close()

        # Add a TOC bookmark
        doc = fitz.open(str(pdf_path))
        doc.set_toc([[1, "Introduction", 1], [1, "Chapter 1", 2]])
        pdf_with_toc = tmp_path / "test_build_toc.pdf"
        doc.save(str(pdf_with_toc))
        doc.close()

        # Use the version with TOC from now on
        pdf_path = pdf_with_toc

        # Create BlobForge zip with marker-style content
        content = "# Introduction\n\nIntro text.\n\n# Chapter 1\n\nChapter content."
        zip_path = self._create_blobforge_zip(
            tmp_path,
            content,
            info={"hash": "buildtest123"},
        )

        # Import
        result = import_blobforge(
            pdf_path=str(pdf_path),
            config=config,
            zip_path=str(zip_path),
        )
        source_id = result["source_id"]
        assert result["status"] == "imported"

        # Run pipeline steps (extract_text should use cached marker output)
        extract_toc(source_id, config)
        extract_pl(source_id, config)
        build_section_tree(source_id, config)

        # This is the key test: extract_text should find the cached
        # marker_full_md.md and NOT call Marker (which isn't installed in test env)
        extracted = extract_text(source_id, config, engine="marker")

        # Should have sections with content from the cached marker output
        assert len(extracted) > 0
        # At least one section should have the content from our mock marker output
        has_content = any("Intro text" in v or "Chapter content" in v for v in extracted.values())
        assert has_content, f"No sections contain expected content: {list(extracted.values())[:3]}"