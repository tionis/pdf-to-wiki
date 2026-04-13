"""Tests for text extraction."""

from __future__ import annotations

from pathlib import Path

from conftest import create_test_pdf

from rulebook_wiki.config import WikiConfig
from rulebook_wiki.ingest.extract_text import extract_text
from rulebook_wiki.ingest.extract_toc import extract_toc
from rulebook_wiki.ingest.extract_page_labels import extract_page_labels
from rulebook_wiki.ingest.build_section_tree import build_section_tree
from rulebook_wiki.ingest.register_pdf import register_pdf


def _run_pipeline_to_section_tree(pdf_path: str, config: WikiConfig) -> None:
    """Helper: run the pipeline up to section-tree build."""
    source = register_pdf(pdf_path, config)
    extract_toc(source.source_id, config)
    extract_page_labels(source.source_id, config)
    build_section_tree(source.source_id, config)


class TestExtractText:
    def test_extract_text_basic(self, tmp_path: Path, config: WikiConfig):
        """Extract text for sections and verify it's non-empty."""
        pdf_path = tmp_path / "book.pdf"
        toc = [
            [1, "Chapter 1", 1],
            [1, "Chapter 2", 3],
        ]
        create_test_pdf(pdf_path, num_pages=6, toc_entries=toc)

        _run_pipeline_to_section_tree(str(pdf_path), config)
        result = extract_text("book", config)

        assert len(result) == 2
        # Each section should have some content (the test PDF has "Page N" text)
        for sid, text in result.items():
            assert isinstance(text, str)

    def test_extract_text_persists(self, tmp_path: Path, config: WikiConfig):
        """Extracted text should be cached."""
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc)

        _run_pipeline_to_section_tree(str(pdf_path), config)
        result1 = extract_text("book", config)
        result2 = extract_text("book", config)
        assert result1 == result2

    def test_extract_text_force(self, tmp_path: Path, config: WikiConfig):
        """Force re-extraction should work."""
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc)

        _run_pipeline_to_section_tree(str(pdf_path), config)
        extract_text("book", config)
        result = extract_text("book", config, force=True)
        assert len(result) == 1

    def test_extract_text_no_section_tree(self, tmp_path: Path, config: WikiConfig):
        """Should raise ValueError if section tree hasn't been built."""
        import pytest

        pdf_path = tmp_path / "book.pdf"
        create_test_pdf(pdf_path, num_pages=5)
        register_pdf(str(pdf_path), config)

        with pytest.raises(ValueError, match="No section tree"):
            extract_text("book", config)

    def test_extract_text_unregistered(self, tmp_path: Path, config: WikiConfig):
        """Should raise ValueError for unregistered source."""
        import pytest

        with pytest.raises(ValueError, match="No registered PDF"):
            extract_text("nonexistent", config)