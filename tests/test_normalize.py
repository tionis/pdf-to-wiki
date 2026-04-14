"""Tests for text repair and normalization."""

from __future__ import annotations

from rulebook_wiki.repair.normalize import (
    repair_text,
    fix_ocr_word_breaks,
    normalize_bullets,
    normalize_whitespace,
    annotate_page_references,
)


class TestFixOcrWordBreaks:
    def test_tion_split(self):
        text = "vio lence"
        result = fix_ocr_word_breaks(text)
        assert "violence" in result

    def test_ment_split(self):
        text = "assign ment"
        result = fix_ocr_word_breaks(text)
        assert "assignment" in result

    def test_ence_split(self):
        text = "consequ ence"
        result = fix_ocr_word_breaks(text)
        assert "consequence" in result

    def test_ing_split(self):
        text = "attack ing"
        result = fix_ocr_word_breaks(text)
        assert "attacking" in result

    def test_ly_split(self):
        text = "quick ly"
        result = fix_ocr_word_breaks(text)
        assert "quickly" in result

    def test_no_false_positive_capitalized(self):
        """Should not join capitalized words (could be names/places)."""
        text = "Fort Worth"
        result = fix_ocr_word_breaks(text)
        # "Fort Worth" should remain — Capital+space+Capital is not an OCR split
        assert "Fort Worth" in result

    def test_ous_split(self):
        text = "danger ous"
        result = fix_ocr_word_breaks(text)
        assert "dangerous" in result

    def test_preserves_real_spaces(self):
        """Real word boundaries should not be affected."""
        text = "the quick brown fox"
        result = fix_ocr_word_breaks(text)
        assert "the quick brown fox" in result


class TestNormalizeBullets:
    def test_bullet_dot(self):
        text = "• First item\n• Second item"
        result = normalize_bullets(text)
        assert "- First item" in result
        assert "- Second item" in result

    def test_nested_bullet(self):
        text = "• Top\n  ◦ Nested"
        result = normalize_bullets(text)
        assert "- Top" in result
        assert "  - Nested" in result

    def test_no_bullets(self):
        text = "Just a paragraph"
        result = normalize_bullets(text)
        assert result == text


class TestNormalizeWhitespace:
    def test_collapse_blank_lines(self):
        text = "Para 1\n\n\n\n\nPara 2"
        result = normalize_whitespace(text)
        assert "\n\n\n" not in result
        assert "Para 1" in result
        assert "Para 2" in result

    def test_trailing_whitespace(self):
        text = "Line 1   \nLine 2  "
        result = normalize_whitespace(text)
        assert "Line 1\nLine 2\n" == result

    def test_ends_with_newline(self):
        result = normalize_whitespace("Hello")
        assert result.endswith("\n")


class TestAnnotatePageReferences:
    def test_p_dot_number(self):
        text = "See p. 43 for details"
        result = annotate_page_references(text)
        assert "{{page-ref:43}}" in result

    def test_pp_dot_range(self):
        text = "See pp. 43-45 for details"
        result = annotate_page_references(text)
        assert "{{page-ref:43-45}}" in result

    def test_see_page_number(self):
        text = "see page 12"
        result = annotate_page_references(text)
        assert "{{page-ref:12}}" in result


class TestRepairText:
    def test_full_pipeline(self):
        text = "vio lence p. 43   \n\n\n\n\n• First item\nEnd"
        result = repair_text(text)
        assert "violence" in result
        assert "- " in result  # bullet normalized
        assert "{{page-ref:43}}" in result
        assert "\n\n\n" not in result