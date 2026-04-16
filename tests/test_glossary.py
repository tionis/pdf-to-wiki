"""Tests for glossary extraction from extracted text."""

from __future__ import annotations

import pytest

from pdf_to_wiki.models import SectionNode, SectionTree
from pdf_to_wiki.repair.extract_glossary import (
    GlossaryEntry,
    StructuredField,
    extract_glossary,
    extract_structured_fields,
    _extract_emdash_definitions,
    _extract_emdash_outside_definitions,
    _extract_colon_definitions,
    _extract_field_values,
    _is_lexicon_section,
    _is_valid_term,
    STRUCTURED_FIELD_LABELS,
)


def _make_tree(source_id: str = "test", nodes: dict | None = None) -> SectionTree:
    """Create a minimal SectionTree for testing."""
    if nodes is None:
        nodes = {
            f"{source_id}/lexicon": SectionNode(
                section_id=f"{source_id}/lexicon",
                source_id=source_id,
                title="Lexicon",
                slug="lexicon",
                level=2,
                parent_id=f"{source_id}/intro",
                children=[],
                pdf_page_start=20,
                pdf_page_end=25,
            ),
            f"{source_id}/intro": SectionNode(
                section_id=f"{source_id}/intro",
                source_id=source_id,
                title="Introduction",
                slug="intro",
                level=1,
                parent_id=None,
                children=[f"{source_id}/lexicon"],
                pdf_page_start=1,
                pdf_page_end=30,
            ),
            f"{source_id}/merits": SectionNode(
                section_id=f"{source_id}/merits",
                source_id=source_id,
                title="Merits",
                slug="merits",
                level=1,
                parent_id=None,
                children=[],
                pdf_page_start=100,
                pdf_page_end=150,
            ),
        }
    return SectionTree(source_id=source_id, nodes=nodes, root_ids=[f"{source_id}/intro", f"{source_id}/merits"])


# ── Em-dash definitions (inside bold) ─────────────────────────────────


class TestEmdashDefinitions:
    """Tests for **Term —** definition extraction."""

    def test_basic_emdash_inside_bold(self):
        text = "**Action —** A task that takes all of a character's time and attention."
        results = _extract_emdash_definitions(text)
        assert len(results) == 1
        assert results[0][0] == "Action"
        assert "task" in results[0][1]

    def test_multiple_emdash_entries(self):
        text = (
            "# Lexicon\n\n"
            "**10 Again —** A result of 10 on any die.\n\n"
            "**8 Again —** A result of 8 or higher.\n\n"
            "**action —** A task that takes time.\n\n"
        )
        results = _extract_emdash_definitions(text)
        assert len(results) == 3
        terms = [r[0] for r in results]
        assert "10 Again" in terms
        assert "8 Again" in terms
        assert "action" in terms

    def test_emdash_with_parenthetical(self):
        text = "**aggravated (damage) —** A damage point that inflicts a grievous wound."
        results = _extract_emdash_definitions(text)
        assert len(results) == 1
        assert "aggravated (damage)" in results[0][0]

    def test_endash_also_works(self):
        """En-dash should also be recognized inside bold."""
        text = "**Action –** A task that takes time."
        results = _extract_emdash_definitions(text)
        assert len(results) == 1
        assert results[0][0] == "Action"


class TestEmdashOutsideDefinitions:
    """Tests for **Term** — definition extraction (em-dash outside bold)."""

    def test_basic_emdash_outside(self):
        text = "**Initiation Benefits** — New recruits receive training."
        results = _extract_emdash_outside_definitions(text)
        assert len(results) == 1
        assert results[0][0] == "Initiation Benefits"
        assert "training" in results[0][1]

    def test_skip_structured_fields(self):
        """Structured field labels should be skipped."""
        text = "**Effect** — Grants +2 to Physical rolls."
        results = _extract_emdash_outside_definitions(text)
        assert len(results) == 0


class TestColonDefinitions:
    """Tests for **Term**: definition extraction."""

    def test_basic_colon_definition(self):
        text = "**Drawback**: Once per chapter, the Storyteller can force a vision."
        results = _extract_colon_definitions(text)
        assert len(results) == 1
        assert results[0][0] == "Drawback"
        assert "Storyteller" in results[0][1]

    def test_skip_marker_page_refs(self):
        """Marker page-reference artifacts should be filtered by _is_valid_term."""
        text = "**[(p.21)](#page-21-0)**: See page 21 for details."
        results = _extract_colon_definitions(text)
        # The low-level extractor returns the raw term; filtering happens in extract_glossary
        # Verify the term is caught by _is_valid_term
        for term, defn in results:
            assert not _is_valid_term(term, defn), f"{term!r} should be invalid"

    def test_skip_see_also_refs(self):
        text = "**[(see p. 280)](#page-280-0)**: Details on page 280."
        results = _extract_colon_definitions(text)
        for term, defn in results:
            assert not _is_valid_term(term, defn), f"{term!r} should be invalid"


class TestStructuredFields:
    """Tests for **Field:** extraction."""

    def test_effect_field(self):
        text = "**Effect:** Grants +2 to all Physical rolls for the scene."
        results = _extract_field_values(text)
        assert len(results) == 1
        assert results[0][0] == "Effect"
        assert "Grants" in results[0][1]

    def test_prerequisites_field(self):
        text = "**Prerequisites:** Strength 3, Brawl 2"
        results = _extract_field_values(text)
        assert len(results) == 1
        assert results[0][0] == "Prerequisites"

    def test_multiple_fields_one_section(self):
        text = (
            "**Effect:** Grants +2 bonus.\n"
            "**Prerequisites:** Strength 3.\n"
            "**Cost:** 2 Experience.\n"
        )
        results = _extract_field_values(text)
        assert len(results) == 3
        labels = [r[0] for r in results]
        assert "Effect" in labels
        assert "Prerequisites" in labels
        assert "Cost" in labels

    def test_unknown_field_skipped(self):
        text = "**CustomLabel:** Some custom value here."
        results = _extract_field_values(text)
        assert len(results) == 0  # Not in STRUCTURED_FIELD_LABELS

    def test_extract_structured_fields_function(self):
        tree = _make_tree()
        text = {
            f"{tree.source_id}/merits": "**Effect:** Grants +2 to Physical rolls.\n**Prerequisites:** Strength 3."
        }
        fields = extract_structured_fields(text, tree)
        assert len(fields) == 2
        assert all(isinstance(f, StructuredField) for f in fields)
        assert fields[0].section_id == f"{tree.source_id}/merits"


class TestValidTerm:
    """Tests for _is_valid_term filtering."""

    def test_valid_term(self):
        assert _is_valid_term("Attribute", "A character trait representing innate capabilities.") is True

    def test_too_short(self):
        assert _is_valid_term("A", "Some definition.") is False

    def test_false_positive(self):
        assert _is_valid_term("Example", "Some definition text here.") is False

    def test_structured_field_label(self):
        assert _is_valid_term("Effect", "Grants +2 to Physical rolls.") is False

    def test_marker_artifact(self):
        assert _is_valid_term("(p.21)", "Some text about page 21.") is False

    def test_marker_span(self):
        assert _is_valid_term("#page-21-0", "Some page reference.") is False

    def test_definition_too_short(self):
        assert _is_valid_term("Term", "Short") is False

    def test_numeric_only_term(self):
        assert _is_valid_term("123", "Some definition text.") is False


class TestIsLexiconSection:
    """Tests for lexicon section detection."""

    def test_by_section_id(self):
        assert _is_lexicon_section("test/lexicon", "# Lexicon\n...") is True

    def test_by_glossary_section_id(self):
        assert _is_lexicon_section("test/glossary", "# Glossary\n...") is True

    def test_by_heading(self):
        assert _is_lexicon_section("test/intro", "# Lexicon\n**Term —** Definition") is True

    def test_by_entry_count(self):
        """5+ em-dash entries = lexicon section."""
        text = "# Something\n"
        for i in range(5):
            text += f"**Term{i} —** Definition {i}.\n\n"
        assert _is_lexicon_section("test/other", text) is True

    def test_not_lexicon(self):
        assert _is_lexicon_section("test/rules", "# Rules\nSome normal text.") is False


class TestExtractGlossary:
    """Integration tests for the full extract_glossary function."""

    def test_lexicon_extraction(self):
        tree = _make_tree()
        text = {
            f"{tree.source_id}/lexicon": (
                "# Lexicon\n\n"
                "**Action —** A task that takes all of a character's time and attention.\n\n"
                "**Attribute —** A character trait representing innate capabilities in three categories.\n\n"
                "**Defense —** An advantage trait determined by the lowest of Dexterity or Wits.\n\n"
            ),
        }
        entries = extract_glossary(text, tree)
        assert len(entries) == 3
        terms = [e.term for e in entries]
        assert "Action" in terms
        assert "Attribute" in terms
        assert "Defense" in terms

    def test_inline_extraction(self):
        tree = _make_tree()
        text = {
            f"{tree.source_id}/merits": (
                "**Encyclopedic Knowledge**: The character has read extensively.\n"
                "**Holistic Awareness**: The character can sense the supernatural.\n"
            ),
        }
        entries = extract_glossary(text, tree)
        assert len(entries) >= 2
        terms = [e.term for e in entries]
        assert "Encyclopedic Knowledge" in terms
        assert "Holistic Awareness" in terms

    def test_lexicon_overrides_inline(self):
        """Lexicon entries should take priority over inline definitions."""
        tree = _make_tree()
        text = {
            f"{tree.source_id}/lexicon": "**action —** A task that takes time and attention during gameplay (lexicon version).\n\n",
            f"{tree.source_id}/merits": "**action**: A task (inline version that differs).\n",
        }
        entries = extract_glossary(text, tree)
        action_entry = [e for e in entries if e.term.lower() == "action"][0]
        assert action_entry.source_type == "lexicon"
        assert "lexicon version" in action_entry.definition

    def test_structured_fields_excluded(self):
        """Structured field labels should not appear in glossary."""
        tree = _make_tree()
        text = {
            f"{tree.source_id}/merits": (
                "**Effect:** Grants +2 to Physical rolls.\n"
                "**Prerequisites:** Strength 3.\n"
            ),
        }
        entries = extract_glossary(text, tree)
        terms = [e.term for e in entries]
        assert "Effect" not in terms
        assert "Prerequisites" not in terms

    def test_empty_text_handled(self):
        tree = _make_tree()
        entries = extract_glossary({f"{tree.source_id}/lexicon": ""}, tree)
        assert len(entries) == 0

    def test_deduplication_by_lowercase(self):
        """Terms should be deduplicated case-insensitively."""
        tree = _make_tree()
        text = {
            f"{tree.source_id}/lexicon": "**Action —** A task that takes time.\n\n",
            f"{tree.source_id}/merits": "**action**: A task (inline).\n",
        }
        entries = extract_glossary(text, tree)
        action_entries = [e for e in entries if e.term.lower() == "action"]
        assert len(action_entries) == 1  # Deduplicated

    def test_sorted_alphabetically(self):
        tree = _make_tree()
        text = {
            f"{tree.source_id}/lexicon": (
                "**Zebra —** A striped equine mammal native to the African savanna.\n\n"
                "**Apple —** A common fruit produced by deciduous trees in temperate climates.\n\n"
                "**Mango —** A tropical stone fruit with sweet golden flesh and leathery skin.\n\n"
            ),
        }
        entries = extract_glossary(text, tree)
        terms = [e.term for e in entries]
        assert terms == ["Apple", "Mango", "Zebra"]


class TestGlossaryEntry:
    """Tests for GlossaryEntry data structure."""

    def test_to_dict(self):
        entry = GlossaryEntry(
            term="Attribute",
            definition="A character trait.",
            section_id="test/lexicon",
            page=20,
            source_type="lexicon",
        )
        d = entry.to_dict()
        assert d["term"] == "Attribute"
        assert d["definition"] == "A character trait."
        assert d["section_id"] == "test/lexicon"
        assert d["page"] == 20
        assert d["source_type"] == "lexicon"

    def test_repr(self):
        entry = GlossaryEntry(term="Action", definition="A task.", source_type="lexicon")
        assert "Action" in repr(entry)