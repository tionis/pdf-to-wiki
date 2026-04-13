"""Tests for TOC extraction."""

from __future__ import annotations

from pathlib import Path

from conftest import create_test_pdf

from rulebook_wiki.config import WikiConfig
from rulebook_wiki.ingest.extract_toc import extract_toc
from rulebook_wiki.ingest.register_pdf import register_pdf


class TestExtractToc:
    def test_extract_toc_basic(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        # PyMuPDF set_toc entries: [level, title, page_1based]
        toc = [
            [1, "Chapter 1: Introduction", 1],
            [2, "Overview", 2],
            [1, "Chapter 2: Characters", 4],
        ]
        create_test_pdf(pdf_path, toc_entries=toc)

        register_pdf(str(pdf_path), config)
        entries = extract_toc("book", config)

        assert len(entries) == 3
        assert entries[0].level == 1
        assert entries[0].title == "Chapter 1: Introduction"
        assert entries[0].pdf_page == 0  # 0-based
        assert entries[1].level == 2
        assert entries[1].title == "Overview"
        assert entries[1].pdf_page == 1  # 0-based
        assert entries[2].level == 1
        assert entries[2].pdf_page == 3  # 0-based

    def test_extract_toc_persists(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, toc_entries=toc)

        register_pdf(str(pdf_path), config)
        extract_toc("book", config)

        # Should be cached
        entries = extract_toc("book", config)
        assert len(entries) == 1

    def test_extract_toc_force(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, toc_entries=toc)

        register_pdf(str(pdf_path), config)
        extract_toc("book", config)
        entries = extract_toc("book", config, force=True)
        assert len(entries) == 1

    def test_extract_toc_unregistered(self, tmp_path: Path, config: WikiConfig):
        import pytest
        with pytest.raises(ValueError, match="No registered PDF"):
            extract_toc("nonexistent", config)

    def test_extract_toc_no_toc(self, tmp_path: Path, config: WikiConfig):
        """PDF with no bookmarks should return empty list."""
        pdf_path = tmp_path / "book.pdf"
        create_test_pdf(pdf_path, toc_entries=None)

        register_pdf(str(pdf_path), config)
        entries = extract_toc("book", config)
        assert entries == []

class TestTocTitleNormalization:
    def test_newlines_collapsed(self, tmp_path: Path, config: WikiConfig):
        """TOC titles with embedded newlines should have them collapsed to spaces."""
        pdf_path = tmp_path / "book.pdf"
        # PyMuPDF set_toc entries: [level, title, page_1based]
        toc = [
            [1, "Step 4: (Optional)\nConsider Complications", 1],
            [2, "Destroyed Reputation\n(Social)", 2],
        ]
        create_test_pdf(pdf_path, toc_entries=toc)

        register_pdf(str(pdf_path), config)
        entries = extract_toc("book", config)

        assert entries[0].title == "Step 4: (Optional) Consider Complications"
        assert entries[1].title == "Destroyed Reputation (Social)"

    def test_multiple_spaces_collapsed(self, tmp_path: Path, config: WikiConfig):
        """Multiple whitespace chars in titles should be collapsed to single spaces."""
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Hello   World", 1]]
        create_test_pdf(pdf_path, toc_entries=toc)

        register_pdf(str(pdf_path), config)
        entries = extract_toc("book", config)

        assert entries[0].title == "Hello World"
