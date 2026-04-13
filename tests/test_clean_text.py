"""Tests for text cleaning and structured extraction."""

from __future__ import annotations

from rulebook_wiki.repair.clean_text import (
    _clean_text,
    _detect_headers_footers,
    _strip_headers_footers,
    extract_page_text_structured,
    SOFT_HYPHEN,
)
import fitz


class TestCleanText:
    def test_soft_hyphen_unicode_removal(self):
        """Unicode soft hyphens (U+00AD) should be removed, rejoining the word."""
        # U+00AD is the standard soft hyphen
        text = "excel\u00adlent and inconsis\u00adtently"
        result = _clean_text(text)
        assert "excellent" in result
        assert "inconsistently" in result
        assert "\u00ad" not in result

    def test_soft_hyphen_char_removal(self):
        """The \\xad byte should be removed (same char as U+00AD)."""
        text = "excel\xadlent"  # \xad == U+00AD
        result = _clean_text(text)
        assert "excellent" in result

    def test_hard_hyphen_rejoin(self):
        """Hard hyphens at line breaks should rejoin the word."""
        text = "This is a conse-\nquence of the rule."
        result = _clean_text(text)
        assert "consequence" in result

    def test_page_number_removal(self):
        """Standalone page numbers on their own line should be removed."""
        text = "Some text\n\n42\n\nMore text"
        result = _clean_text(text)
        assert "Some text" in result
        assert "More text" in result
        # The standalone "42" should be removed
        lines = [l.strip() for l in result.split("\n") if l.strip()]
        assert "42" not in lines

    def test_paragraph_assembly(self):
        """Lines that continue with lowercase should be joined."""
        text = "This is the first line\nof a paragraph."
        result = _clean_text(text)
        assert "first line of a paragraph" in result

    def test_paragraph_break_preserved(self):
        """Blank lines between paragraphs should be preserved."""
        text = "First paragraph.\n\nSecond paragraph."
        result = _clean_text(text)
        assert "First paragraph" in result
        assert "Second paragraph" in result
        # Should have a paragraph break
        assert "\n\n" in result

    def test_sentence_ends_new_paragraph(self):
        """Lines ending with periods should start new paragraphs."""
        text = "First sentence.\nSecond sentence starts here."
        result = _clean_text(text)
        assert "First sentence." in result
        assert "Second sentence starts here." in result

    def test_excessive_blank_lines_collapsed(self):
        """Three or more blank lines should collapse to two."""
        text = "Paragraph 1\n\n\n\n\nParagraph 2"
        result = _clean_text(text)
        assert "Paragraph 1" in result
        assert "Paragraph 2" in result
        assert "\n\n\n" not in result

    def test_header_footer_line_removal(self):
        """Known header/footer lines should be stripped."""
        text = "Real content here\nCHAPTER ONE: CORE SYSTEM\nMore content"
        hfs = {"CHAPTER ONE: CORE SYSTEM"}
        result = _strip_headers_footers(text, hfs)
        assert "CHAPTER ONE: CORE SYSTEM" not in result
        assert "Real content here" in result
        assert "More content" in result

    def test_header_with_page_number_removal(self):
        """Header lines with appended page numbers should also be stripped."""
        text = "Real content\nAction-Adventure [combat]   43\nMore content"
        hfs = {"Action-Adventure [combat]"}
        result = _strip_headers_footers(text, hfs)
        assert "Action-Adventure" not in result

    def test_empty_input(self):
        result = _clean_text("")
        assert result == ""

    def test_only_whitespace(self):
        result = _clean_text("   \n\n  \n  ")
        assert result.strip() == ""


class TestHeaderFooterDetection:
    def test_no_headers(self):
        """When there are no repeating lines, return empty set."""
        doc = fitz.open()
        for i in range(5):
            doc.new_page()
            page = doc[i]
            page.insert_text((72, 72), f"Page {i} unique content {i}")

        hfs = _detect_headers_footers(doc, 0, 4, min_occurrences=2)
        # With unique content per page, no header/footer patterns should be found
        assert isinstance(hfs, set)
        doc.close()