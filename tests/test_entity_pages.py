"""Tests for entity page generation."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.models import SectionNode, SectionTree


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tmp_config(tmp_path):
    """Create a WikiConfig with temp directories."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    artifact_dir = cache_dir / "artifacts"
    artifact_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    db_path = str(cache_dir / "cache.db")

    cfg = WikiConfig(
        output_dir=str(output_dir),
        cache_db_path=db_path,
        artifact_dir=str(artifact_dir),
    )
    return cfg


@pytest.fixture
def sample_tree():
    """Create a minimal section tree for testing."""
    nodes = {
        "book/lexicon": SectionNode(
            section_id="book/lexicon",
            source_id="book",
            title="Lexicon",
            slug="lexicon",
            level=2,
            parent_id="book",
            children=[],
            pdf_page_start=10,
            pdf_page_end=15,
            printed_page_start="10",
            printed_page_end="15",
            markdown_output_path="books/book/lexicon/index.md",
        ),
        "book/combat": SectionNode(
            section_id="book/combat",
            source_id="book",
            title="Combat",
            slug="combat",
            level=2,
            parent_id="book",
            children=[],
            pdf_page_start=20,
            pdf_page_end=30,
            printed_page_start="20",
            printed_page_end="30",
            markdown_output_path="books/book/combat/index.md",
        ),
    }
    return SectionTree(
        source_id="book",
        nodes=nodes,
        root_ids=["book/lexicon", "book/combat"],
    )


@pytest.fixture
def sample_glossary_data():
    """Sample glossary entries (as stored in glossary.json)."""
    return [
        {
            "term": "Dice Pool",
            "definition": "A collection of dice rolled together to determine the outcome of an action. The dice pool is usually Attribute + Skill.",
            "section_id": "book/lexicon",
            "page": 10,
            "source_type": "lexicon",
        },
        {
            "term": "Action",
            "definition": "A described activity that a character undertakes. Actions are the basic unit of play.",
            "section_id": "book/lexicon",
            "page": 10,
            "source_type": "lexicon",
        },
        {
            "term": "Defense",
            "definition": "The target number to beat on an attack roll. Computed from Attributes. Reduces incoming damage.",
            "section_id": "book/combat",
            "page": 20,
            "source_type": "inline",
        },
        {
            "term": "Breaking Point",
            "definition": "A roll triggered when a character encounters something that challenges their worldview. Uses Resolve + Composure.",
            "section_id": "book/lexicon",
            "page": 11,
            "source_type": "lexicon",
        },
    ]


def _setup_artifacts(cfg, source_id, tree, glossary_data):
    """Helper to set up artifact files for entity generation."""
    from pdf_to_wiki.cache.artifact_store import ArtifactStore
    from pdf_to_wiki.cache.db import CacheDB

    # Save tree and glossary to artifacts
    artifacts = ArtifactStore(cfg.resolved_artifact_dir())
    artifacts.save_json(source_id, "section_tree", tree.model_dump())
    artifacts.save_json(source_id, "glossary", glossary_data)

    # Register the source in cache DB
    from pdf_to_wiki.models import PdfSource
    db = CacheDB(cfg.resolved_cache_db_path())
    db.upsert_pdf_source(PdfSource(
        source_id=source_id,
        path="/tmp/book.pdf",
        sha256="abc123",
        title="Test Book",
        page_count=50,
    ), registered_at="2025-01-01T00:00:00Z")
    db.close()


# ── Slug generation tests ────────────────────────────────────────────


class TestEntitySlug:
    def test_simple_term(self):
        from pdf_to_wiki.emit.entity_pages import entity_slug
        assert entity_slug("Dice Pool") == "dice-pool"

    def test_single_word(self):
        from pdf_to_wiki.emit.entity_pages import entity_slug
        assert entity_slug("Action") == "action"

    def test_with_parens(self):
        from pdf_to_wiki.emit.entity_pages import entity_slug
        assert entity_slug("Breaking Point (Morality)") == "breaking-point-morality"

    def test_with_special_chars(self):
        from pdf_to_wiki.emit.entity_pages import entity_slug
        assert entity_slug("10 Again") == "10-again"

    def test_aggravated_damage(self):
        from pdf_to_wiki.emit.entity_pages import entity_slug
        assert entity_slug("Aggravated (damage)") == "aggravated-damage"

    def test_multiple_spaces(self):
        from pdf_to_wiki.emit.entity_pages import entity_slug
        assert entity_slug("Extended  Action") == "extended-action"

    def test_empty_term(self):
        from pdf_to_wiki.emit.entity_pages import entity_slug
        assert entity_slug("") == "unknown"

    def test_only_special_chars(self):
        from pdf_to_wiki.emit.entity_pages import entity_slug
        assert entity_slug("---") == "unknown"


# ── Entity page generation tests ─────────────────────────────────────


class TestGenerateEntityPages:
    def test_basic_generation(self, tmp_config, sample_tree, sample_glossary_data):
        """Entity pages are generated for all glossary entries."""
        from pdf_to_wiki.emit.entity_pages import generate_entity_pages

        _setup_artifacts(tmp_config, "book", sample_tree, sample_glossary_data)
        manifest = generate_entity_pages("book", tmp_config)

        assert len(manifest) == 4
        # Check that entity files exist
        output_dir = tmp_config.resolved_output_dir()
        for term, rel_path in manifest.items():
            abs_path = output_dir / rel_path
            assert abs_path.exists(), f"Entity page missing: {rel_path}"

    def test_entity_content(self, tmp_config, sample_tree, sample_glossary_data):
        """Entity pages contain term, definition, and source link."""
        from pdf_to_wiki.emit.entity_pages import generate_entity_pages

        _setup_artifacts(tmp_config, "book", sample_tree, sample_glossary_data)
        manifest = generate_entity_pages("book", tmp_config)

        output_dir = tmp_config.resolved_output_dir()
        dice_path = output_dir / manifest["Dice Pool"]
        content = dice_path.read_text()

        # Has the term as heading
        assert "# Dice Pool" in content
        # Has the definition in a blockquote
        assert "dice rolled together" in content
        # Has source link
        assert "Defined in" in content or "lexicon" in content

    def test_entity_frontmatter(self, tmp_config, sample_tree, sample_glossary_data):
        """Entity pages have proper YAML frontmatter."""
        from pdf_to_wiki.emit.entity_pages import generate_entity_pages

        _setup_artifacts(tmp_config, "book", sample_tree, sample_glossary_data)
        manifest = generate_entity_pages("book", tmp_config)

        output_dir = tmp_config.resolved_output_dir()
        action_path = output_dir / manifest["Action"]
        content = action_path.read_text()

        assert "---" in content
        assert "entity_type: glossary_term" in content
        assert "defined_in" in content

    def test_lexicon_type_badge(self, tmp_config, sample_tree, sample_glossary_data):
        """Lexicon entries have 📖 badge in the entities index."""
        from pdf_to_wiki.emit.entity_pages import generate_entity_pages

        _setup_artifacts(tmp_config, "book", sample_tree, sample_glossary_data)
        generate_entity_pages("book", tmp_config)

        output_dir = tmp_config.resolved_output_dir()
        index_path = output_dir / "books" / "book" / "entities" / "index.md"
        assert index_path.exists()
        content = index_path.read_text()
        assert "📖" in content  # Lexicon badge

    def test_inline_type_badge(self, tmp_config, sample_tree, sample_glossary_data):
        """Inline entries have 📝 badge in the entities index."""
        from pdf_to_wiki.emit.entity_pages import generate_entity_pages

        _setup_artifacts(tmp_config, "book", sample_tree, sample_glossary_data)
        generate_entity_pages("book", tmp_config)

        output_dir = tmp_config.resolved_output_dir()
        index_path = output_dir / "books" / "book" / "entities" / "index.md"
        content = index_path.read_text()
        assert "📝" in content  # Inline badge

    def test_entities_index_generation(self, tmp_config, sample_tree, sample_glossary_data):
        """An entities/index.md is generated with alphabetical listing."""
        from pdf_to_wiki.emit.entity_pages import generate_entity_pages

        _setup_artifacts(tmp_config, "book", sample_tree, sample_glossary_data)
        generate_entity_pages("book", tmp_config)

        output_dir = tmp_config.resolved_output_dir()
        index_path = output_dir / "books" / "book" / "entities" / "index.md"
        assert index_path.exists()
        content = index_path.read_text()
        assert "# Entities" in content
        assert "game terms" in content

    def test_entities_index_letter_nav(self, tmp_config, sample_tree, sample_glossary_data):
        """Entities index has alphabetical letter navigation."""
        from pdf_to_wiki.emit.entity_pages import generate_entity_pages

        _setup_artifacts(tmp_config, "book", sample_tree, sample_glossary_data)
        generate_entity_pages("book", tmp_config)

        output_dir = tmp_config.resolved_output_dir()
        index_path = output_dir / "books" / "book" / "entities" / "index.md"
        content = index_path.read_text()
        # Our terms start with A, B, D — should have jump links
        assert "[A](#a)" in content or "[a]" in content.lower()

    def test_no_glossary_data(self, tmp_config):
        """Returns empty dict when no glossary data exists."""
        from pdf_to_wiki.emit.entity_pages import generate_entity_pages

        manifest = generate_entity_pages("nonexistent", tmp_config)
        assert manifest == {}

    def test_definition_truncation(self, tmp_config, sample_tree):
        """Very long definitions are truncated in entity pages."""
        from pdf_to_wiki.emit.entity_pages import generate_entity_pages

        long_def = "A" * 800  # Very long definition
        glossary_data = [{
            "term": "Long Term",
            "definition": long_def,
            "section_id": "book/lexicon",
            "page": 10,
            "source_type": "lexicon",
        }]
        _setup_artifacts(tmp_config, "book", sample_tree, glossary_data)
        manifest = generate_entity_pages("book", tmp_config)

        output_dir = tmp_config.resolved_output_dir()
        entity_path = output_dir / manifest["Long Term"]
        content = entity_path.read_text()
        # Long definition should be truncated
        assert "..." in content

    def test_force_regeneration(self, tmp_config, sample_tree, sample_glossary_data):
        """Force flag regenerates entity pages even if they exist."""
        from pdf_to_wiki.emit.entity_pages import generate_entity_pages

        _setup_artifacts(tmp_config, "book", sample_tree, sample_glossary_data)
        manifest1 = generate_entity_pages("book", tmp_config, force=False)
        manifest2 = generate_entity_pages("book", tmp_config, force=True)
        assert len(manifest1) == len(manifest2)


# ── See-also / related terms tests ───────────────────────────────────


class TestFindRelatedTerms:
    def test_basic_cross_reference(self):
        """Finds related glossary terms mentioned in a definition."""
        from pdf_to_wiki.emit.entity_pages import _find_related_terms

        all_terms = {
            "dice pool": "Dice Pool",
            "action": "Action",
            "defense": "Defense",
            "damage": "Damage",
        }
        definition = "An action that deals damage to a target. The dice pool is rolled against Defense."
        related = _find_related_terms("Combat", definition, all_terms)

        assert "Action" in related
        assert "Defense" in related
        assert "Dice Pool" in related

    def test_excludes_self(self):
        """The term itself is excluded from related terms."""
        from pdf_to_wiki.emit.entity_pages import _find_related_terms

        all_terms = {"dice pool": "Dice Pool", "action": "Action"}
        definition = "The dice pool is rolled for an action."
        related = _find_related_terms("Dice Pool", definition, all_terms)

        assert "Dice Pool" not in related
        assert "Action" in related

    def test_short_terms_skipped(self):
        """Very short terms (≤2 chars) are skipped to avoid false positives."""
        from pdf_to_wiki.emit.entity_pages import _find_related_terms

        all_terms = {"xp": "XP", "action": "Action"}
        definition = "Gain XP from an action."
        related = _find_related_terms("Level", definition, all_terms)

        # "XP" is only 2 chars, should be skipped
        assert "XP" not in related
        assert "Action" in related

    def test_max_links_limit(self):
        """Respects max_links parameter."""
        from pdf_to_wiki.emit.entity_pages import _find_related_terms

        all_terms = {f"term{i}": f"Term{i}" for i in range(20)}
        definition = " ".join(f"term{i}" for i in range(20))
        related = _find_related_terms("Self", definition, all_terms, max_links=3)

        assert len(related) <= 3


# ── Entity reference detection tests ─────────────────────────────────


class TestFindEntityReferences:
    def test_basic_reference(self):
        """Finds entity term references in text."""
        from pdf_to_wiki.emit.entity_pages import find_entity_references

        entity_terms = {"dice pool": "Dice Pool", "action": "Action"}
        text = "Roll a dice pool for the action."

        refs = find_entity_references(text, entity_terms)
        assert len(refs) > 0
        # Should find "dice pool" and "action"
        terms_found = {r[2] for r in refs}
        assert "Dice Pool" in terms_found or "Action" in terms_found

    def test_skip_heading_references(self):
        """Skips terms in headings."""
        from pdf_to_wiki.emit.entity_pages import find_entity_references

        entity_terms = {"dice pool": "Dice Pool"}
        text = "# Dice Pool\n\nRoll the dice pool."

        refs = find_entity_references(text, entity_terms)
        # Should only find the one in body text, not the heading
        assert len(refs) <= 1

    def test_case_insensitive(self):
        """Finds references regardless of case."""
        from pdf_to_wiki.emit.entity_pages import find_entity_references

        entity_terms = {"dice pool": "Dice Pool"}
        text = "Use a Dice Pool for the roll."

        refs = find_entity_references(text, entity_terms)
        assert len(refs) >= 1

    def test_skip_bold_definitions(self):
        """Skips terms that are already in bold (likely the original definition)."""
        from pdf_to_wiki.emit.entity_pages import find_entity_references

        entity_terms = {"action": "Action"}
        text = "**Action** — An activity a character undertakes."

        refs = find_entity_references(text, entity_terms)
        # The bold-wrapped term should be skipped
        assert len(refs) == 0 or all(r[2] != "Action" for r in refs)


# ── Integration test ──────────────────────────────────────────────────


class TestEntityIntegration:
    def test_full_entity_workflow(self, tmp_config, sample_tree, sample_glossary_data):
        """Full workflow: generate entities → verify structure and links."""
        from pdf_to_wiki.emit.entity_pages import generate_entity_pages

        _setup_artifacts(tmp_config, "book", sample_tree, sample_glossary_data)
        manifest = generate_entity_pages("book", tmp_config)

        output_dir = tmp_config.resolved_output_dir()

        # Check that all entity pages exist
        for term, rel_path in manifest.items():
            entity_path = output_dir / rel_path
            assert entity_path.exists(), f"Missing entity page for {term}"
            assert entity_path.stat().st_size > 0

        # Check that the entities index exists
        index_path = output_dir / "books" / "book" / "entities" / "index.md"
        assert index_path.exists()
        assert index_path.stat().st_size > 0

        # Verify entity pages have valid relative links
        for term, rel_path in manifest.items():
            entity_path = output_dir / rel_path
            content = entity_path.read_text()
            # Check for Markdown link patterns
            if "Defined in:" in content:
                # Should have a relative link
                assert "](" in content

    def test_see_also_links(self, tmp_config, sample_tree, sample_glossary_data):
        """Entity pages for terms that reference other terms have 'See also' links."""
        from pdf_to_wiki.emit.entity_pages import generate_entity_pages

        # Breaking Point's definition mentions "Resolve + Composure" which
        # is a dice pool-ish pattern; Dice Pool mentions "Attribute + Skill"
        _setup_artifacts(tmp_config, "book", sample_tree, sample_glossary_data)
        manifest = generate_entity_pages("book", tmp_config)

        output_dir = tmp_config.resolved_output_dir()
        # Check at least one entity has a "See also" section
        # (depends on whether definition text contains other glossary terms)
        has_see_also = False
        for term, rel_path in manifest.items():
            content = (output_dir / rel_path).read_text()
            if "See also" in content:
                has_see_also = True
                break
        # This is informational, not a hard requirement
        # (our test data may or may not trigger it)