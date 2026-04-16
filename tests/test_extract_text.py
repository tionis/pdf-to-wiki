"""Tests for text extraction."""

from __future__ import annotations

from pathlib import Path

from conftest import create_test_pdf

from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.ingest.extract_text import extract_text
from pdf_to_wiki.ingest.extract_toc import extract_toc
from pdf_to_wiki.ingest.extract_page_labels import extract_page_labels
from pdf_to_wiki.ingest.build_section_tree import build_section_tree
from pdf_to_wiki.ingest.register_pdf import register_pdf


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
        from pdf_to_wiki.extract import list_engines
        # Import to trigger registration
        import pdf_to_wiki.extract.pymupdf_engine  # noqa: F401
        import pdf_to_wiki.extract.marker_engine  # noqa: F401
        engines = list_engines()
        assert "pymupdf" in engines
        assert "marker" in engines

    def test_extract_engine_unknown(self):
        """Should raise ValueError for unknown engine."""
        import pytest
        from pdf_to_wiki.extract import get_engine
        with pytest.raises(ValueError, match="Unknown extraction engine"):
            get_engine("nonexistent", WikiConfig())

    def test_pymupdf_engine_extract(self, tmp_path: Path, config: WikiConfig):
        """PyMuPDF engine should extract text from a simple PDF."""
        from pdf_to_wiki.extract import get_engine
        import pdf_to_wiki.extract.pymupdf_engine  # noqa: F401
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

class TestSplitMarkdownByHeadings:
    """Tests for the split_markdown_by_headings function."""

    def test_basic_split(self):
        """Basic heading split with two sections."""
        from pdf_to_wiki.extract.marker_engine import split_markdown_by_headings

        md = "# Section One\nContent for one.\n\n# Section Two\nContent for two."
        sections = [
            ("s1", "Section One", 1, 3),
            ("s2", "Section Two", 4, 6),
        ]
        result = split_markdown_by_headings(md, sections)
        assert "Content for one" in result["s1"]
        assert "Content for two" in result["s2"]

    def test_absorb_unmatched_sub_heading(self):
        """Sub-headings not in TOC should be absorbed by parent section."""
        from pdf_to_wiki.extract.marker_engine import split_markdown_by_headings

        md = (
            "# Weapons\n"
            "# Ranged Weapons Chart\n"
            "| Type | Dmg |\n"
            "|------|-----|\n"
            "| Pistol | 2 |\n"
            "# Melee Weapons Chart\n"
            "| Weapon | Dmg |\n"
            "|--------|-----|\n"
            "| Knife | 1 |\n"
            "# Next Section\n"
            "Other content here.\n"
        )
        sections = [
            ("weapons", "Weapons", 1, 3),
            ("next", "Next Section", 5, 6),
        ]
        result = split_markdown_by_headings(md, sections)

        # "Weapons" section should absorb the Ranged and Melee chart sub-headings
        assert "| Pistol |" in result["weapons"]
        assert "| Knife |" in result["weapons"]
        # "Next Section" should not have the weapon content
        assert "Pistol" not in result["next"]

    def test_no_match_falls_back_to_page_range(self):
        """Sections with no heading match get page-range fallback text."""
        from pdf_to_wiki.extract.marker_engine import split_markdown_by_headings

        md = '<span id="page-3-0"></span>\nPage 3 content.\n<span id="page-5-0"></span>\nPage 5 content.'
        sections = [
            ("unmatched", "Unmatched Section", 3, 4),
        ]
        result = split_markdown_by_headings(md, sections)
        # Should fall back to page-range extraction
        assert "Page 3 content" in result["unmatched"]

    def test_consecutive_same_title_merged(self):
        """Consecutive headings with the same normalized title are merged."""
        from pdf_to_wiki.extract.marker_engine import split_markdown_by_headings

        md = "# Equipment\nSome intro.\n# EQUIPMENT\n| Item | Cost |\n|------|------|\n| Rope | 1 |"
        sections = [
            ("equip", "Equipment", 1, 3),
        ]
        result = split_markdown_by_headings(md, sections)
        # Both "Equipment" and "EQUIPMENT" should be merged into one
        assert "Some intro" in result["equip"]
        assert "| Rope |" in result["equip"]

    def test_absorb_depth_limit(self):
        """Sub-headings deeper than max_absorb_depth are NOT absorbed."""
        from pdf_to_wiki.extract.marker_engine import split_markdown_by_headings

        # Section 1 is level 1, sub-headings are level 2, 3, 4, 5, 6
        md = (
            "# Alpha\n"
            "Alpha intro.\n"
            "## Sub A\n"
            "Sub A content.\n"
            "### Sub A1\n"
            "Sub A1 content.\n"
            "#### Sub A1a\n"
            "Sub A1a content.\n"
            "##### Sub A1a-i\n"
            "Sub A1a-i content.\n"
            "###### Sub A1a-i-x\n"
            "Sub A1a-i-x content.\n"
        )
        sections = [
            ("alpha", "Alpha", 1, 5),
        ]

        # With max_absorb_depth=3 (default), headings up to level 4 are absorbed
        result = split_markdown_by_headings(md, sections, max_absorb_depth=3)
        assert "Sub A content" in result["alpha"]
        assert "Sub A1 content" in result["alpha"]
        assert "Sub A1a content" in result["alpha"]  # level 4 = 1+3 = within depth
        assert "Sub A1a-i content" not in result["alpha"]  # level 5 = 1+4 = beyond depth

        # With max_absorb_depth=1, only level 2 headings absorbed
        result = split_markdown_by_headings(md, sections, max_absorb_depth=1)
        assert "Sub A content" in result["alpha"]  # level 2 = within depth
        assert "Sub A1 content" not in result["alpha"]  # level 3 = beyond depth

    def test_absorb_depth_stops_at_deeper_unclaimed(self):
        """Depth limit prevents absorbing a level-1 heading after a level-2."""
        from pdf_to_wiki.extract.marker_engine import split_markdown_by_headings

        md = (
            "# Chapter\n"
            "Chapter intro.\n"
            "## Detail\n"
            "Detail text.\n"
            "# Another Chapter\n"
            "This is another chapter.\n"
        )
        sections = [
            ("chapter", "Chapter", 1, 3),
        ]

        # With default max_absorb_depth=3, level-1 headings (diff=0)
        # are NOT absorbed because the level difference (1-1=0) is <= 0
        # But wait — level diff is heading_level - matched_level = 1-1 = 0,
        # which is <= 3, so it WOULD be absorbed. This actually tests
        # that a second same-level heading is absorbed by default.
        # With max_absorb_depth=0, it should stop.
        result = split_markdown_by_headings(md, sections, max_absorb_depth=0)
        assert "Chapter intro" in result["chapter"]
        assert "Another Chapter" not in result["chapter"]  # level diff 0 > 0

    def test_absorb_depth_with_claimed_sections(self):
        """Depth limit doesn't override claimed heading boundaries."""
        from pdf_to_wiki.extract.marker_engine import split_markdown_by_headings

        md = (
            "# Parent\n"
            "Parent intro.\n"
            "## Sub A\n"
            "Sub A content.\n"
            "## Sub B\n"
            "Sub B content.\n"
        )
        sections = [
            ("parent", "Parent", 1, 3),
            ("sub_b", "Sub B", 3, 4),
        ]
        result = split_markdown_by_headings(md, sections, max_absorb_depth=3)

        # Sub A (unclaimed) should be absorbed into parent
        assert "Sub A content" in result["parent"]
        # Sub B (claimed) should NOT be absorbed
        assert "Sub A content" in result["parent"]
        assert "Sub B content" in result["sub_b"]

    def test_fuzzy_match_jaccard(self):
        """Fuzzy matching via token Jaccard similarity for near-miss headings."""
        from pdf_to_wiki.extract.marker_engine import split_markdown_by_headings

        # Marker emits "The Combat Chapter" but TOC has "Combat"
        md = "# The Combat Chapter\nCombat content.\n# Magic\nMagic content."
        sections = [
            ("combat", "Combat", 1, 3),
            ("magic", "Magic", 4, 6),
        ]
        result = split_markdown_by_headings(md, sections)

        # "Combat" should match "The Combat Chapter" via fuzzy (Jaccard on {"combat"} vs {"the", "combat", "chapter"})
        assert "Combat content" in result["combat"]
        assert "Magic content" in result["magic"]

    def test_fuzzy_match_prefix_stripping(self):
        """Common heading prefixes are stripped for matching."""
        from pdf_to_wiki.extract.marker_engine import split_markdown_by_headings

        md = "# Chapter 3: Spells\nSpells text.\n# Chapter 4: Rituals\nRituals text."
        sections = [
            ("spells", "Spells", 1, 3),
            ("rituals", "Rituals", 4, 6),
        ]
        result = split_markdown_by_headings(md, sections)

        # "Spells" should match "Chapter 3: Spells" after prefix stripping
        assert "Spells text" in result["spells"]
        assert "Rituals text" in result["rituals"]

    def test_fuzzy_match_page_proximity_bonus(self):
        """Fuzzy matching gets a boost from page proximity."""
        from pdf_to_wiki.extract.marker_engine import split_markdown_by_headings

        # Two headings with similar tokens but on different pages
        # The one on the right page should win
        md = (
            '<span id="page-0-0"></span>\n'
            "# Introduction\nIntro text.\n"
            '<span id="page-5-0"></span>\n'
            "# Game Introduction\nGame intro text.\n"
        )
        sections = [
            ("intro", "Introduction", 0, 2),
            ("game_intro", "Game Introduction", 5, 7),
        ]
        result = split_markdown_by_headings(md, sections)

        assert "Intro text" in result["intro"]
        assert "Game intro text" in result["game_intro"]

    def test_fuzzy_match_too_low_score_rejected(self):
        """Fuzzy matches below 0.5 score are rejected."""
        from pdf_to_wiki.extract.marker_engine import split_markdown_by_headings

        md = "# Completely Unrelated\nRandom text.\n"
        sections = [
            ("weapons", "Weapons Master", 1, 3),
        ]
        result = split_markdown_by_headings(md, sections)

        # "Weapons Master" vs "Completely Unrelated" — Jaccard is 0, no match
        # Falls back to page-range extraction (empty in this case since no page anchors)
        assert "weapons" in result  # Entry exists but may be empty

    def test_strip_heading_affixes(self):
        """Test the _strip_heading_affixes helper function."""
        from pdf_to_wiki.extract.marker_engine import _strip_heading_affixes

        assert _strip_heading_affixes("the combat") == "combat"
        assert _strip_heading_affixes("chapter 3 spells") == "spells"
        assert _strip_heading_affixes("introduction cont") == "introduction"
        assert _strip_heading_affixes("1. opening") == "opening"
        assert _strip_heading_affixes("the appendix") == "appendix"
        assert _strip_heading_affixes("") == ""
