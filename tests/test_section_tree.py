"""Tests for section tree construction."""

from __future__ import annotations

from pathlib import Path

from conftest import create_test_pdf

from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.ingest.build_section_tree import build_section_tree, _slugify
from pdf_to_wiki.ingest.extract_page_labels import extract_page_labels
from pdf_to_wiki.ingest.extract_toc import extract_toc
from pdf_to_wiki.ingest.register_pdf import register_pdf


class TestSlugify:
    def test_simple(self):
        assert _slugify("Introduction") == "introduction"

    def test_spaces_and_caps(self):
        assert _slugify("Chapter 1: Introduction") == "chapter-1-introduction"

    def test_special_chars(self):
        s = _slugify("What's New? (3rd Edition)")
        assert all(c.isalnum() or c == "-" for c in s)

    def test_empty(self):
        assert _slugify("") == "untitled"

    def test_unicode(self):
        result = _slugify("Ünïcödé")
        assert isinstance(result, str)
        assert len(result) > 0


class TestBuildSectionTree:
    def test_basic_tree(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [
            [1, "Chapter 1: Introduction", 1],
            [2, "Overview", 2],
            [2, "Getting Started", 3],
            [1, "Chapter 2: Characters", 5],
            [2, "Attributes", 5],
            [2, "Skills", 8],
        ]
        create_test_pdf(pdf_path, num_pages=10, toc_entries=toc)

        register_pdf(str(pdf_path), config)
        extract_toc("book", config)
        extract_page_labels("book", config)

        tree = build_section_tree("book", config)

        # Should have 6 nodes
        assert len(tree.nodes) == 6
        assert len(tree.root_ids) == 2

        # Root sections
        ch1_id = tree.root_ids[0]
        ch2_id = tree.root_ids[1]

        ch1 = tree.nodes[ch1_id]
        assert "chapter-1-introduction" in ch1_id
        assert ch1.level == 1
        assert len(ch1.children) == 2

        ch2 = tree.nodes[ch2_id]
        assert "chapter-2-characters" in ch2_id
        assert ch2.level == 1
        assert len(ch2.children) == 2

    def test_page_ranges(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [
            [1, "Chapter 1", 1],
            [1, "Chapter 2", 5],
            [1, "Chapter 3", 9],
        ]
        create_test_pdf(pdf_path, num_pages=10, toc_entries=toc)

        register_pdf(str(pdf_path), config)
        extract_toc("book", config)
        extract_page_labels("book", config)

        tree = build_section_tree("book", config)

        ch1 = tree.nodes[tree.root_ids[0]]
        ch2 = tree.nodes[tree.root_ids[1]]
        ch3 = tree.nodes[tree.root_ids[2]]

        assert ch1.pdf_page_start == 0
        assert ch1.pdf_page_end == 3  # Before ch2 starts (0-based: page 4 is ch2)
        assert ch2.pdf_page_start == 4
        assert ch2.pdf_page_end == 7  # Before ch3 starts (0-based: page 8 is ch3)
        assert ch3.pdf_page_start == 8
        assert ch3.pdf_page_end == 9  # Last page

    def test_parent_child_relationships(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [
            [1, "Chapter 1", 1],
            [2, "Section A", 2],
            [3, "Subsection A1", 2],
            [2, "Section B", 4],
        ]
        create_test_pdf(pdf_path, num_pages=6, toc_entries=toc)

        register_pdf(str(pdf_path), config)
        extract_toc("book", config)
        extract_page_labels("book", config)

        tree = build_section_tree("book", config)

        ch1 = tree.nodes[tree.root_ids[0]]
        # Chapter 1 should have 2 children: Section A, Section B
        assert len(ch1.children) == 2

        sec_a_id = ch1.children[0]
        sec_a = tree.nodes[sec_a_id]
        assert sec_a.parent_id == ch1.section_id
        assert len(sec_a.children) == 1  # Subsection A1

        sub_a1 = tree.nodes[sec_a.children[0]]
        assert sub_a1.parent_id == sec_a.section_id

    def test_tree_caches(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc)

        register_pdf(str(pdf_path), config)
        extract_toc("book", config)
        extract_page_labels("book", config)

        tree1 = build_section_tree("book", config)
        tree2 = build_section_tree("book", config)
        assert tree1.source_id == tree2.source_id

    def test_tree_force_rebuild(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc)

        register_pdf(str(pdf_path), config)
        extract_toc("book", config)
        extract_page_labels("book", config)

        build_section_tree("book", config)
        tree = build_section_tree("book", config, force=True)
        assert len(tree.nodes) == 1

    def test_missing_toc_data(self, tmp_path: Path, config: WikiConfig):
        """If toc step hasn't been run, should raise ValueError."""
        pdf_path = tmp_path / "book.pdf"
        create_test_pdf(pdf_path, num_pages=5)

        register_pdf(str(pdf_path), config)

        import pytest
        with pytest.raises(ValueError, match="No TOC data"):
            build_section_tree("book", config)