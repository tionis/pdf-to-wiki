"""Tests for page reference rewriting (Markdown relative links)."""

from __future__ import annotations

from rulebook_wiki.models import SectionNode, SectionTree
from rulebook_wiki.repair.rewrite_refs import rewrite_page_references


def _make_node(sid, title, start, end, children=None, parent=None) -> SectionNode:
    return SectionNode(
        source_id="test-book",
        section_id=sid,
        title=title,
        slug=sid.split("/")[-1],
        level=2,
        pdf_page_start=start,
        pdf_page_end=end,
        parent_id=parent,
        children=children or [],
        printed_page_start=str(start),
        printed_page_end=str(end),
    )


class TestRewritePageReferences:
    def test_basic_reference_with_context(self):
        """With current_note_path, generates relative link."""
        nodes = {
            "test-book/combat": _make_node(
                "test-book/combat", "Combat", 43, 47,
                children=["test-book/combat/damage"],
            ),
            "test-book/combat/damage": _make_node(
                "test-book/combat/damage", "Damage", 44, 45,
                parent="test-book/combat",
            ),
        }
        tree = SectionTree(source_id="test-book", nodes=nodes, root_ids=["test-book/combat"])
        text = "See {{page-ref:44}} for details"
        result = rewrite_page_references(
            text, tree,
            current_note_path="books/test-book/combat/index.md",
        )
        # Should be a relative link from index.md to damage.md
        assert "[Damage]" in result
        assert "damage.md" in result
        assert "{{page-ref:44}}" not in result

    def test_basic_reference_without_context(self):
        """Without current_note_path, generates absolute link."""
        nodes = {
            "test-book/combat": _make_node(
                "test-book/combat", "Combat", 43, 47,
                children=["test-book/combat/damage"],
            ),
            "test-book/combat/damage": _make_node(
                "test-book/combat/damage", "Damage", 44, 45,
                parent="test-book/combat",
            ),
        }
        tree = SectionTree(source_id="test-book", nodes=nodes, root_ids=["test-book/combat"])
        text = "See {{page-ref:44}} for details"
        result = rewrite_page_references(text, tree)
        assert "[Damage]" in result
        assert "damage.md" in result
        assert "{{page-ref:44}}" not in result

    def test_relative_link_same_directory(self):
        """Links within same directory should be simple filenames."""
        nodes = {
            "test-book/combat": _make_node(
                "test-book/combat", "Combat", 43, 47,
                children=["test-book/combat/damage", "test-book/combat/defense"],
            ),
            "test-book/combat/damage": _make_node(
                "test-book/combat/damage", "Damage", 44, 45,
                parent="test-book/combat",
            ),
            "test-book/combat/defense": _make_node(
                "test-book/combat/defense", "Defense", 43, 43,
                parent="test-book/combat",
            ),
        }
        tree = SectionTree(source_id="test-book", nodes=nodes, root_ids=["test-book/combat"])
        # damage.md and defense.md are both in books/test-book/combat/
        text = "See {{page-ref:43}}"
        result = rewrite_page_references(
            text, tree,
            current_note_path="books/test-book/combat/damage.md",
        )
        assert "[Defense](defense.md)" in result

    def test_relative_link_different_directory(self):
        """Links to different directory should use ../ paths."""
        nodes = {
            "test-book/chapter-one": _make_node(
                "test-book/chapter-one", "Chapter One", 40, 50,
                children=["test-book/chapter-one/combat"],
            ),
            "test-book/chapter-one/combat": _make_node(
                "test-book/chapter-one/combat", "Combat", 43, 47,
                children=["test-book/chapter-one/combat/damage"],
                parent="test-book/chapter-one",
            ),
            "test-book/chapter-one/combat/damage": _make_node(
                "test-book/chapter-one/combat/damage", "Damage", 44, 45,
                parent="test-book/chapter-one/combat",
            ),
            "test-book/chapter-two": _make_node(
                "test-book/chapter-two", "Chapter Two", 51, 60,
            ),
        }
        tree = SectionTree(
            source_id="test-book",
            nodes=nodes,
            root_ids=["test-book/chapter-one", "test-book/chapter-two"],
        )
        text = "See {{page-ref:44}}"
        result = rewrite_page_references(
            text, tree,
            current_note_path="books/test-book/chapter-two/index.md",
        )
        # From chapter-two/ to chapter-one/combat/damage.md
        assert "[Damage]" in result
        assert "chapter-one" in result

    def test_multiple_sections_prefers_leaf(self):
        nodes = {
            "test-book/combat": _make_node(
                "test-book/combat", "Combat", 43, 47,
                children=["test-book/combat/damage"],
            ),
            "test-book/combat/damage": _make_node(
                "test-book/combat/damage", "Damage", 44, 45,
                parent="test-book/combat",
            ),
        }
        tree = SectionTree(source_id="test-book", nodes=nodes, root_ids=["test-book/combat"])
        text = "See {{page-ref:44}}"
        result = rewrite_page_references(text, tree)
        # Should prefer the leaf section "Damage" over parent "Combat"
        assert "[Damage]" in result
        assert "damage" in result

    def test_no_matching_section(self):
        nodes = {
            "test-book/intro": _make_node("test-book/intro", "Intro", 1, 10),
        }
        tree = SectionTree(source_id="test-book", nodes=nodes, root_ids=["test-book/intro"])
        text = "See {{page-ref:999}}"
        result = rewrite_page_references(text, tree)
        # Should keep annotation when no section matches
        assert "{{page-ref:999}}" in result

    def test_no_tree(self):
        """Without tree, references should remain as annotations."""
        from rulebook_wiki.repair.normalize import repair_text
        text = "See p. 43 for details"
        result = repair_text(text, tree=None)
        assert "{{page-ref:43}}" in result