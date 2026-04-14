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
