"""Tests for Markdown skeleton emission."""

from __future__ import annotations

from pathlib import Path

from conftest import create_test_pdf

from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.emit.markdown_writer import emit_skeleton
from pdf_to_wiki.ingest.build_section_tree import build_section_tree
from pdf_to_wiki.ingest.extract_page_labels import extract_page_labels
from pdf_to_wiki.ingest.extract_toc import extract_toc
from pdf_to_wiki.ingest.register_pdf import register_pdf


def _run_full_pipeline(pdf_path: str, config: WikiConfig) -> None:
    """Helper: run the full pipeline up to section-tree build."""
    from pdf_to_wiki.ingest.register_pdf import register_pdf as reg
    from pdf_to_wiki.ingest.extract_toc import extract_toc as toc
    from pdf_to_wiki.ingest.extract_page_labels import extract_page_labels as epl
    from pdf_to_wiki.ingest.build_section_tree import build_section_tree as bst

    source = reg(pdf_path, config)
    toc(source.source_id, config)
    epl(source.source_id, config)
    bst(source.source_id, config)


class TestEmitSkeleton:
    def test_emits_files(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [
            [1, "Chapter 1: Introduction", 1],
            [2, "Overview", 2],
            [1, "Chapter 2: Characters", 5],
        ]
        create_test_pdf(pdf_path, num_pages=10, toc_entries=toc)

        _run_full_pipeline(str(pdf_path), config)
        manifest = emit_skeleton("book", config)

        assert len(manifest) == 3
        # Check that files were actually created
        output_dir = config.resolved_output_dir()
        for sid, rel_path in manifest.items():
            assert (output_dir / rel_path).exists(), f"Missing file: {output_dir / rel_path}"

    def test_frontmatter(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc)

        _run_full_pipeline(str(pdf_path), config)
        manifest = emit_skeleton("book", config)

        # Read the emitted file and check frontmatter
        output_dir = config.resolved_output_dir()
        ch1_path = list(manifest.values())[0]
        content = (output_dir / ch1_path).read_text()

        assert "---" in content
        assert "source_pdf" in content
        assert "section_id" in content
        assert "level" in content
        assert "pdf_page_start" in content
        assert "pdf_page_end" in content
        assert "parent_section_id" in content

    def test_deterministic(self, tmp_path: Path, config: WikiConfig):
        """Running emit twice should produce identical output."""
        pdf_path = tmp_path / "book.pdf"
        toc = [
            [1, "Chapter 1", 1],
            [1, "Chapter 2", 3],
        ]
        create_test_pdf(pdf_path, num_pages=6, toc_entries=toc)

        _run_full_pipeline(str(pdf_path), config)
        manifest1 = emit_skeleton("book", config)

        # Read content
        output_dir = config.resolved_output_dir()
        content1 = {}
        for sid, path in manifest1.items():
            content1[sid] = (output_dir / path).read_text()

        # Re-emit with force
        manifest2 = emit_skeleton("book", config, force=True)
        content2 = {}
        for sid, path in manifest2.items():
            content2[sid] = (output_dir / path).read_text()

        # Same paths and same content
        assert set(manifest1.keys()) == set(manifest2.keys())
        for sid in manifest1:
            assert content1[sid] == content2[sid], f"Content differs for {sid}"

    def test_tree_section_is_leaf(self, tmp_path: Path, config: WikiConfig):
        """A section without children should become a .md file, not a directory."""
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc)

        _run_full_pipeline(str(pdf_path), config)
        manifest = emit_skeleton("book", config)

        # Chapter 1 has no children → it's a leaf → file
        ch1_id = list(manifest.keys())[0]
        assert manifest[ch1_id].endswith(".md")
        assert "/index.md" not in manifest[ch1_id]

    def test_section_with_children(self, tmp_path: Path, config: WikiConfig):
        """A section with children should emit as a directory with index.md."""
        pdf_path = tmp_path / "book.pdf"
        toc = [
            [1, "Chapter 1", 1],
            [2, "Section A", 1],
            [2, "Section B", 3],
        ]
        create_test_pdf(pdf_path, num_pages=6, toc_entries=toc)

        _run_full_pipeline(str(pdf_path), config)
        manifest = emit_skeleton("book", config)

        ch1_id = [sid for sid in manifest if "chapter-1" in sid][0]
        # Chapter 1 has children → directory with index.md
        assert "/index.md" in manifest[ch1_id]

    def test_cached_skip(self, tmp_path: Path, config: WikiConfig):
        """Second call without force should be cached."""
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc)

        _run_full_pipeline(str(pdf_path), config)
        manifest1 = emit_skeleton("book", config)
        manifest2 = emit_skeleton("book", config)
        assert manifest1 == manifest2

    def test_stale_file_cleanup(self, tmp_path: Path, config: WikiConfig):
        """Changing the section tree and re-emitting should remove old files."""
        # Start with a simple TOC
        pdf_path = tmp_path / "book.pdf"
        toc_v1 = [
            [1, "Chapter 1", 1],
            [2, "Section A", 1],
            [2, "Section B", 3],
            [1, "Chapter 2", 5],
        ]
        create_test_pdf(pdf_path, num_pages=10, toc_entries=toc_v1)
        _run_full_pipeline(str(pdf_path), config)
        manifest1 = emit_skeleton("book", config)

        output_dir = config.resolved_output_dir()
        # Verify section-b exists
        sec_b_path = [p for sid, p in manifest1.items() if "section-b" in sid]
        assert len(sec_b_path) == 1
        sec_b_file = output_dir / sec_b_path[0]
        assert sec_b_file.exists()

        # Now re-register with a different TOC that removes Section B
        toc_v2 = [
            [1, "Chapter 1", 1],
            [2, "Section A", 1],
            [1, "Chapter 2", 5],
        ]
        create_test_pdf(pdf_path, num_pages=10, toc_entries=toc_v2)
        # Force re-register and re-build (same source_id, new PDF content)
        from pdf_to_wiki.ingest.register_pdf import register_pdf as reg
        from pdf_to_wiki.ingest.extract_toc import extract_toc as toc
        from pdf_to_wiki.ingest.extract_page_labels import extract_page_labels as epl
        from pdf_to_wiki.ingest.build_section_tree import build_section_tree as bst
        source = reg(str(pdf_path), config)  # Re-register (updates SHA)
        toc(source.source_id, config, force=True)  # Force re-extract TOC
        epl(source.source_id, config, force=True)
        bst(source.source_id, config, force=True)  # Force rebuild tree
        manifest2 = emit_skeleton("book", config, force=True)

        # Section B should have been cleaned up
        assert not sec_b_file.exists(), f"Stale file should be removed: {sec_b_file}"


class TestEmitFilters:
    """Tests for --sections and --page-range filters."""

    def test_page_range_filter(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [
            [1, "Chapter 1", 1],
            [1, "Chapter 2", 5],
            [1, "Chapter 3", 10],
        ]
        create_test_pdf(pdf_path, num_pages=15, toc_entries=toc)
        _run_full_pipeline(str(pdf_path), config)

        # Filter to pages 0-6 (0-based) → should include chapters 1 and 2
        manifest = emit_skeleton("book", config, force=True, page_filter=(0, 6))
        # Chapter 3 starts at page 9 (0-based) — should be excluded
        assert any("chapter-3" not in sid for sid in manifest.keys())
        assert len(manifest) == 2

    def test_section_filter_by_slug(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [
            [1, "Chapter 1", 1],
            [1, "Chapter 2", 5],
            [1, "Chapter 3", 10],
        ]
        create_test_pdf(pdf_path, num_pages=15, toc_entries=toc)
        _run_full_pipeline(str(pdf_path), config)

        # Filter by slug
        manifest = emit_skeleton("book", config, force=True, section_filter=["chapter-2"])
        assert len(manifest) == 1
        assert any("chapter-2" in sid for sid in manifest.keys())

    def test_section_filter_by_title(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [
            [1, "Introduction", 1],
            [1, "Combat Rules", 5],
            [1, "Magic", 10],
        ]
        create_test_pdf(pdf_path, num_pages=15, toc_entries=toc)
        _run_full_pipeline(str(pdf_path), config)

        # Filter by title substring
        manifest = emit_skeleton("book", config, force=True, section_filter=["Rules"])
        assert len(manifest) == 1
        assert any("combat" in sid for sid in manifest.keys())

    def test_no_filter_emits_all(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [
            [1, "Chapter 1", 1],
            [1, "Chapter 2", 5],
        ]
        create_test_pdf(pdf_path, num_pages=10, toc_entries=toc)
        _run_full_pipeline(str(pdf_path), config)

        manifest = emit_skeleton("book", config, force=True)
        assert len(manifest) == 2


class TestDryRun:
    """Tests for --dry-run mode."""

    def test_dry_run_no_files(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1], [1, "Chapter 2", 5]]
        create_test_pdf(pdf_path, num_pages=10, toc_entries=toc)
        _run_full_pipeline(str(pdf_path), config)

        # Enable dry-run
        config.dry_run = True
        manifest = emit_skeleton("book", config, force=True)

        # Should report sections but not write files
        output_dir = config.resolved_output_dir()
        for sid, path in manifest.items():
            assert not (output_dir / path).exists(), f"Dry-run should not write file: {path}"


class TestImageAltText:
    """Tests for image alt text population from section title."""

    def test_empty_alt_populated_from_section_title(self):
        from pdf_to_wiki.emit.markdown_writer import _rewrite_asset_paths
        text = "Some text\n\n![](assets/my-book/page_0_picture_0.png)\n\nMore text"
        result = _rewrite_asset_paths(text, "books/my-book/chapter/section.md", "books", "my-book", section_title="Combat Rules")
        # Empty alt text should be populated with section title
        assert "![Combat Rules](" in result

    def test_existing_alt_preserved(self):
        from pdf_to_wiki.emit.markdown_writer import _rewrite_asset_paths
        text = "![A diagram](assets/my-book/page_0_picture_0.png)"
        result = _rewrite_asset_paths(text, "books/my-book/chapter/section.md", "books", "my-book", section_title="Combat Rules")
        # Existing alt text should NOT be overwritten
        assert "![A diagram](" in result
        assert "![Combat Rules](" not in result

    def test_no_title_keeps_empty_alt(self):
        from pdf_to_wiki.emit.markdown_writer import _rewrite_asset_paths
        text = "![](assets/my-book/page_0_picture_0.png)"
        result = _rewrite_asset_paths(text, "books/my-book/chapter/section.md", "books", "my-book", section_title="")
        # No section title provided — alt remains empty
        assert "![](" in result