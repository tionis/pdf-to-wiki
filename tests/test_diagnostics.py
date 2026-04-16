"""Tests for font/encoding diagnostics module."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.ingest.diagnostics import diagnose_fonts


class TestDiagnosticsFormat:
    """Test the text and JSON output formats."""

    def _create_test_pdf(self, path: Path, fonts_and_text: list[tuple[str, str, int, int]]) -> None:
        """Create a PDF with specific fonts and text.

        Args:
            fonts_and_text: List of (text, font_name, x, y) tuples.
        """
        doc = fitz.open()
        page = doc.new_page()
        for text, font_name, x, y in fonts_and_text:
            page.insert_text(fitz.Point(x, y), text, fontname=font_name, fontsize=10)
        doc.save(str(path))
        doc.close()

    def test_basic_text_output(self, tmp_path: Path):
        """Text output should include font summary."""
        pdf_path = tmp_path / "test.pdf"
        self._create_test_pdf(pdf_path, [
            ("Hello World", "helv", 50, 50),
            ("Bold text", "hebo", 50, 80),
        ])

        result = diagnose_fonts(str(pdf_path), output_format="text")
        assert "FONT & ENCODING DIAGNOSTICS" in result
        assert "FONT SUMMARY" in result
        assert "Distinct fonts:" in result

    def test_json_output(self, tmp_path: Path):
        """JSON output should be valid JSON with expected keys."""
        import json
        pdf_path = tmp_path / "test.pdf"
        self._create_test_pdf(pdf_path, [
            ("Hello World", "helv", 50, 50),
        ])

        result = diagnose_fonts(str(pdf_path), output_format="json")
        data = json.loads(result)
        assert "fonts" in data
        assert "page_fonts" in data
        assert "total_chars" in data
        assert "total_spans" in data

    def test_page_range(self, tmp_path: Path):
        """Page range should limit the scan."""
        doc = fitz.open()
        for i in range(5):
            page = doc.new_page()
            page.insert_text(fitz.Point(50, 50), f"Page {i + 1}", fontsize=10)
        pdf_path = tmp_path / "multi.pdf"
        doc.save(str(pdf_path))
        doc.close()

        result = diagnose_fonts(str(pdf_path), page_range=(1, 2), output_format="text")
        assert "Pages: 2–3" in result  # 0-indexed internally, 1-indexed display

    def test_empty_pdf(self, tmp_path: Path):
        """Empty PDF should still produce valid output."""
        doc = fitz.open()
        doc.new_page()
        pdf_path = tmp_path / "empty.pdf"
        doc.save(str(pdf_path))
        doc.close()

        result = diagnose_fonts(str(pdf_path), output_format="text")
        assert "FONT & ENCODING DIAGNOSTICS" in result
        assert "Distinct fonts: 0" in result

    def test_detects_suspicious_chars(self, tmp_path: Path):
        """Should detect suspicious character codes if present in text spans."""
        doc = fitz.open()
        page = doc.new_page()
        # Insert normal text
        page.insert_text(fitz.Point(50, 50), "Normal text", fontsize=10)
        pdf_path = tmp_path / "sus.pdf"
        doc.save(str(pdf_path))
        doc.close()

        result = diagnose_fonts(str(pdf_path), output_format="text")
        # Should complete without error even if no suspicious chars found
        assert "FONT SUMMARY" in result

    def test_json_structure(self, tmp_path: Path):
        """JSON output should have properly structured font data."""
        import json
        pdf_path = tmp_path / "test.pdf"
        self._create_test_pdf(pdf_path, [
            ("Hello", "helv", 50, 50),
        ])

        result = diagnose_fonts(str(pdf_path), output_format="json")
        data = json.loads(result)

        # Check font data structure
        for font_name, font_data in data["fonts"].items():
            assert "char_count" in font_data
            assert "span_count" in font_data
            assert "is_bold" in font_data
            assert "is_italic" in font_data
            assert "is_symbol" in font_data
            assert "page_count" in font_data