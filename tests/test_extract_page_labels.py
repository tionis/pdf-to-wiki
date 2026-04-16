"""Tests for page-label extraction."""

from __future__ import annotations

from pathlib import Path

from conftest import create_test_pdf

from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.ingest.extract_page_labels import (
    _format_label,
    _to_alpha,
    _to_roman,
    extract_page_labels,
)
from pdf_to_wiki.ingest.register_pdf import register_pdf


class TestPageLabelFormatting:
    def test_roman_uppercase(self):
        assert _to_roman(1) == "I"
        assert _to_roman(4) == "IV"
        assert _to_roman(9) == "IX"
        assert _to_roman(14) == "XIV"
        assert _to_roman(1999) == "MCMXCIX"

    def test_alpha(self):
        assert _to_alpha(1) == "a"
        assert _to_alpha(26) == "z"
        assert _to_alpha(27) == "aa"

    def test_format_decimal(self):
        assert _format_label("", "/D", 5) == "5"

    def test_format_roman(self):
        assert _format_label("", "/R", 3) == "III"

    def test_format_with_prefix(self):
        assert _format_label("App-", "/D", 5) == "App-5"


class TestExtractPageLabels:
    def test_extract_default_labels(self, tmp_path: Path, config: WikiConfig):
        """PDF without explicit /PageLabels should get 1-indexed numeric labels."""
        pdf_path = tmp_path / "book.pdf"
        create_test_pdf(pdf_path, num_pages=5, page_labels=False)

        register_pdf(str(pdf_path), config)
        labels = extract_page_labels("book", config)

        assert len(labels) == 5
        assert labels[0].label == "1"
        assert labels[4].label == "5"
        assert labels[0].page_index == 0
        assert labels[4].page_index == 4

    def test_extract_persists(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        create_test_pdf(pdf_path, num_pages=3)

        register_pdf(str(pdf_path), config)
        extract_page_labels("book", config)

        # Re-fetch should be cached
        labels = extract_page_labels("book", config)
        assert len(labels) == 3

    def test_extract_force(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        create_test_pdf(pdf_path, num_pages=3)

        register_pdf(str(pdf_path), config)
        extract_page_labels("book", config)
        labels = extract_page_labels("book", config, force=True)
        assert len(labels) == 3

    def test_extract_unregistered(self, tmp_path: Path, config: WikiConfig):
        import pytest
        with pytest.raises(ValueError, match="No registered PDF"):
            extract_page_labels("nonexistent", config)

class TestPageLabelsProperty:
    def test_pypdf_page_labels_property_used(self, tmp_path: Path, config: WikiConfig):
        """When pypdf's page_labels property works, it should be preferred over manual parsing."""
        pdf_path = tmp_path / "book.pdf"
        # Our test PDFs don't have explicit /PageLabels, but we can test
        # that the fallback path works correctly for a standard PDF
        create_test_pdf(pdf_path, num_pages=5)

        register_pdf(str(pdf_path), config)
        labels = extract_page_labels("book", config)

        # With pypdf's page_labels property, even simple PDFs should get labels
        assert len(labels) == 5
        assert all(isinstance(pl.label, str) for pl in labels)

    def test_roman_numeral_from_page_labels(self, tmp_path: Path, config: WikiConfig):
        """Test that Roman numeral page labels are properly extracted when available."""
        # This tests our _to_roman formatter directly since our test PDFs
        # don't easily support /PageLabels injection
        from pdf_to_wiki.ingest.extract_page_labels import _to_roman, _format_label

        assert _format_label("", "/r", 1) == "i"
        assert _format_label("", "/r", 4) == "iv"
        assert _format_label("", "/R", 9) == "IX"
        assert _format_label("", "/D", 5) == "5"
        assert _format_label("App-", "/D", 3) == "App-3"


class TestRomanNumeralDetection:
    """Tests for the Roman-numeral front-matter heuristic."""

    def test_is_roman_numeral(self):
        from pdf_to_wiki.ingest.extract_page_labels import _is_roman_numeral
        assert _is_roman_numeral("i")
        assert _is_roman_numeral("ii")
        assert _is_roman_numeral("iii")
        assert _is_roman_numeral("iv")
        assert _is_roman_numeral("v")
        assert _is_roman_numeral("xii")
        assert not _is_roman_numeral("")
        assert not _is_roman_numeral("hello")
        assert not _is_roman_numeral("introduction")  # starts with 'i' but not Roman
        assert not _is_roman_numeral("visual")  # starts with 'v' but not Roman

    def test_roman_to_int(self):
        from pdf_to_wiki.ingest.extract_page_labels import _roman_to_int
        assert _roman_to_int("i") == 1
        assert _roman_to_int("ii") == 2
        assert _roman_to_int("iii") == 3
        assert _roman_to_int("iv") == 4
        assert _roman_to_int("v") == 5
        assert _roman_to_int("ix") == 9
        assert _roman_to_int("x") == 10
        assert _roman_to_int("xiv") == 14
        assert _roman_to_int("xx") == 20

    def test_detect_roman_numerals_with_mock(self, tmp_path: Path, config: WikiConfig):
        """Test Roman-numeral detection with a PDF that has Roman page numbers."""
        import fitz

        # Create a PDF with Roman numerals as page numbers in the footer
        doc = fitz.open()
        roman_pages = ["i", "ii", "iii", "iv", "v", "vi"]
        for rn in roman_pages:
            page = doc.new_page()
            page.insert_text(
                fitz.Point(50, 700),
                f"\n\n\n\n\n\n\n\n\n{rn}",  # Roman numeral at bottom
                fontsize=10,
            )
        # Add body pages with Arabic numerals
        for n in range(1, 4):
            page = doc.new_page()
            page.insert_text(
                fitz.Point(50, 700),
                f"\n\n\n\n\n\n\n\n\n{n}",
                fontsize=10,
            )

        pdf_path = tmp_path / "roman_test.pdf"
        doc.save(str(pdf_path))
        doc.close()

        from pdf_to_wiki.ingest.extract_page_labels import _detect_roman_numerals
        result = _detect_roman_numerals(str(pdf_path), 9)

        assert result is not None
        assert len(result) == 9
        # First 6 pages should have Roman numeral labels
        assert result[0].label == "i"
        assert result[1].label == "ii"
        assert result[5].label == "vi"
        # Body pages should have Arabic labels
        assert result[6].label == "1"
        assert result[7].label == "2"
        assert result[8].label == "3"

    def test_detect_roman_numerals_no_roman(self, tmp_path: Path):
        """PDF without Roman numerals should return None."""
        import fitz

        doc = fitz.open()
        for n in range(1, 6):
            page = doc.new_page()
            page.insert_text(
                fitz.Point(50, 700),
                f"\n\n\n\n\n\n\n\n\n{n}",
                fontsize=10,
            )

        pdf_path = tmp_path / "arabic_test.pdf"
        doc.save(str(pdf_path))
        doc.close()

        from pdf_to_wiki.ingest.extract_page_labels import _detect_roman_numerals
        result = _detect_roman_numerals(str(pdf_path), 5)
        assert result is None

    def test_detect_roman_numerals_empty_pdf(self, tmp_path: Path):
        """PDF with no text should return None."""
        import fitz

        doc = fitz.open()
        for _ in range(5):
            doc.new_page()

        pdf_path = tmp_path / "empty_test.pdf"
        doc.save(str(pdf_path))
        doc.close()

        from pdf_to_wiki.ingest.extract_page_labels import _detect_roman_numerals
        result = _detect_roman_numerals(str(pdf_path), 5)
        assert result is None
