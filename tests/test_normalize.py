"""Tests for text repair and normalization."""

from __future__ import annotations

from pdf_to_wiki.repair.normalize import (
    repair_text,
    fix_ocr_word_breaks,
    normalize_bullets,
    normalize_whitespace,
    annotate_page_references,
    remap_dingbat_bullets,
    clean_marker_artifacts,
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

    def test_dot_rating_preserved(self):
        """•• and ••• (TTRPG dot ratings) should preserve the extra dots."""
        text = "•• Allow ignoring Complications\n••• Gain +3 Enhancement"
        result = normalize_bullets(text)
        assert result == "- • Allow ignoring Complications\n- •• Gain +3 Enhancement"

    def test_single_dot_as_bullet(self):
        """Single • at line start becomes list marker."""
        text = "• Add a +1 Enhancement"
        result = normalize_bullets(text)
        assert result == "- Add a +1 Enhancement"


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

    def test_marker_page_anchors_stripped(self):
        text = 'Before <span id="page-178-0"></span> after'
        result = repair_text(text)
        assert '<span id="page-' not in result
        assert 'Before' in result
        assert 'after' in result

class TestDingbatRemap:
    """Tests for dingbat character remapping using manifest."""

    def test_manifest_overrides_heuristic(self):
        """When a dingbat manifest is provided, it drives the remapping."""
        manifest = {"Y": ["•"]}
        text = "- Y **Competence:** The player characters"
        result = remap_dingbat_bullets(text, dingbat_manifest=manifest)
        assert "- • **Competence:**" in result

    def test_manifest_with_unknown_char(self):
        """Manifest can include characters beyond Y."""
        manifest = {"Y": ["•"], "l": ["●"]}
        text = "- Y First item"
        result = remap_dingbat_bullets(text, dingbat_manifest=manifest)
        assert "- • First item" in result

    def test_no_manifest_uses_heuristic(self):
        """Without a manifest, the heuristic handles FantasyRPGDings Y."""
        text = "- Y **Competence:**"
        result = remap_dingbat_bullets(text)
        assert "- • **Competence:**" in result

    def test_does_not_remap_common_english(self):
        """English words after list markers should NOT be remapped."""
        text = "- You gain a point\n- Yes, this works"
        result = remap_dingbat_bullets(text)
        assert "- You gain a point" in result
        assert "- Yes, this works" in result

    def test_dot_rating_parens(self):
        """(Y), (YY) in parentheses should be remapped to dot ratings."""
        text = "# Sprinter (YY)"
        result = remap_dingbat_bullets(text, dingbat_manifest={"Y": ["•"]})
        assert "(••)" in result

    def test_dot_rating_range(self):
        """(Y to YYY) ranges should be remapped."""
        text = "# Fame (Y to YYY)"
        result = remap_dingbat_bullets(text, dingbat_manifest={"Y": ["•"]})
        assert "(• to •••)" in result

    def test_empty_manifest_preserves_text(self):
        """Empty manifest means no remapping (no dingbats found in PDF)."""
        manifest = {}
        text = "- Y **Competence:**"
        result = remap_dingbat_bullets(text, dingbat_manifest=manifest)
        # With empty manifest, Y is NOT treated as a dingbat
        assert "- Y **Competence:**" in result


class TestCleanMarkerArtifacts:
    """Tests for Marker page-link unwrapping."""

    def test_unwrap_page_ref(self):
        """[\\(p.21\\)](#page-21-0) should become p.21."""
        text = "Momentum [\\(p.21\\)](#page-21-0) to the pool"
        result = clean_marker_artifacts(text)
        assert "(#page-21-0)" not in result
        assert "p.21" in result

    def test_unwrap_see_page(self):
        """[\\(see p. 51\\)](#page-51-0) should become 'see p. 51'."""
        text = "Bonds [\\(see p. 51\\)](#page-51-0)"
        result = clean_marker_artifacts(text)
        assert "(#page-51-0)" not in result
        assert "see p. 51" in result

    def test_unwrap_bare_page_ref(self):
        """Simple page refs like [Chapter Two, p. 62](#page-62-0)."""
        text = "See [Chapter Two, p. 62](#page-62-0)"
        result = clean_marker_artifacts(text)
        assert "(#page-62-0)" not in result
        assert "Chapter Two, p. 62" in result

    def test_br_in_table_converted(self):
        """\u003cbr\u003e in pipe tables should be converted to ' / '."""
        text = "| Fragile\u003cbr\u003eVolatile | 102\u003cbr\u003e102 |"
        result = clean_marker_artifacts(text)
        assert "\u003cbr" not in result
        assert "Fragile / Volatile" in result

    def test_br_in_paragraph_preserved(self):
        """\u003cbr\u003e outside of tables should be left alone (unless it's a block element)."""
        text = "Some text\u003cbr\u003eMore text"
        result = clean_marker_artifacts(text)
        # \u003cbr\u003e outside tables is left as-is (no | delimiters)
        assert '\u003cbr' in result

    def test_br_case_insensitive(self):
        """\u003cBR\u003e and \u003cbr/\u003e variants should be handled."""
        text = "| A\u003cBR\u003eB | C\u003cbr/\u003eD |"
        result = clean_marker_artifacts(text)
        assert "\u003cbr" not in result.lower().replace("/", "")
        assert "A / B" in result
        assert "C / D" in result


class TestAnnotatePageReferencesExtended:
    """Tests for the Wordp. N pattern fix and edge cases."""

    def test_capitalized_term_joined_page_ref(self):
        """'Parkourp. 48' should be split and annotated."""
        text = "**Parkourp. 48**"
        result = annotate_page_references(text)
        assert "{{page-ref:48}}" in result
        assert "Parkour" in result

    def test_multiword_term_joined_page_ref(self):
        """'Driverp. 47' from 'Crack Driverp. 47' should be split."""
        text = "Crack Driverp. 47 for details"
        result = annotate_page_references(text)
        assert "{{page-ref:47}}" in result

    def test_lowercase_word_not_stripped(self):
        """'map. 12' (sentence ending) should NOT be treated as a page ref."""
        text = "Use the map. 12 goblins appear."
        result = annotate_page_references(text)
        # 'map.' is a common word, not a game term — should not be annotated
        assert "{{page-ref:12}}" not in result

    def test_standalone_page_ref_still_works(self):
        """Normal 'p. 43' should still be annotated after the fix."""
        text = "See p. 43 for details"
        result = annotate_page_references(text)
        assert "{{page-ref:43}}" in result
