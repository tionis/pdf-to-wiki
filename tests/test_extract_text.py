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
        # Use pymupdf engine — marker requires ML models
        result = extract_text("book", config, engine="pymupdf")

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
        result1 = extract_text("book", config, engine="pymupdf")
        result2 = extract_text("book", config, engine="pymupdf")
        assert result1 == result2

    def test_extract_text_force(self, tmp_path: Path, config: WikiConfig):
        """Force re-extraction should work."""
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc)

        _run_pipeline_to_section_tree(str(pdf_path), config)
        extract_text("book", config, engine="pymupdf")
        result = extract_text("book", config, force=True, engine="pymupdf")
        assert len(result) == 1

    def test_extract_text_no_section_tree(self, tmp_path: Path, config: WikiConfig):
        """Should raise ValueError if section tree hasn't been built."""
        import pytest

        pdf_path = tmp_path / "book.pdf"
        create_test_pdf(pdf_path, num_pages=5)
        register_pdf(str(pdf_path), config)

        with pytest.raises(ValueError, match="No section tree"):
            extract_text("book", config, engine="pymupdf")

    def test_extract_text_unregistered(self, tmp_path: Path, config: WikiConfig):
        """Should raise ValueError for unregistered source."""
        import pytest

        with pytest.raises(ValueError, match="No registered PDF"):
            extract_text("nonexistent", config, engine="pymupdf")

    def test_extract_engine_registry(self):
        """Engine registry should list pymupdf and marker."""
        from rulebook_wiki.extract import list_engines
        # Import to trigger registration
        import rulebook_wiki.extract.pymupdf_engine  # noqa: F401
        import rulebook_wiki.extract.marker_engine  # noqa: F401
        engines = list_engines()
        assert "pymupdf" in engines
        assert "marker" in engines

    def test_extract_engine_unknown(self):
        """Should raise ValueError for unknown engine."""
        import pytest
        from rulebook_wiki.extract import get_engine
        with pytest.raises(ValueError, match="Unknown extraction engine"):
            get_engine("nonexistent", WikiConfig())

    def test_pymupdf_engine_extract(self, tmp_path: Path, config: WikiConfig):
        """PyMuPDF engine should extract text from a simple PDF."""
        from rulebook_wiki.extract import get_engine
        import rulebook_wiki.extract.pymupdf_engine  # noqa: F401
        import fitz

        # Create a simple test PDF
        pdf_path = tmp_path / "test.pdf"
        doc = fitz.open()
        for i in range(3):
            doc.new_page()
            page = doc[i]
            page.insert_text((72, 72), f"Page {i + 1} content about dragons.")
        doc.save(str(pdf_path))
        doc.close()

        engine = get_engine("pymupdf", config)
        text = engine.extract_page_range(str(pdf_path), 0, 2)
        assert "dragons" in text