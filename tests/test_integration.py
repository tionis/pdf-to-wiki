"""Integration test: full end-to-end pipeline for one PDF."""

from __future__ import annotations

from pathlib import Path

from conftest import create_test_pdf

from rulebook_wiki.config import WikiConfig
from rulebook_wiki.ingest.register_pdf import register_pdf
from rulebook_wiki.ingest.extract_toc import extract_toc
from rulebook_wiki.ingest.extract_page_labels import extract_page_labels
from rulebook_wiki.ingest.build_section_tree import build_section_tree
from rulebook_wiki.emit.markdown_writer import emit_skeleton
from rulebook_wiki.cache.db import CacheDB
from rulebook_wiki.cache.artifact_store import ArtifactStore


class TestEndToEnd:
    def test_full_pipeline(self, tmp_path: Path, config: WikiConfig):
        """Run the complete pipeline on a single PDF and verify outputs."""
        pdf_path = tmp_path / "my-rulebook.pdf"
        toc = [
            [1, "Chapter 1: Introduction", 1],
            [2, "Overview", 1],
            [2, "Getting Started", 3],
            [1, "Chapter 2: Characters", 5],
            [2, "Attributes", 5],
            [3, "Strength", 5],
            [3, "Dexterity", 6],
            [2, "Skills", 8],
            [1, "Chapter 3: Combat", 10],
        ]
        create_test_pdf(pdf_path, title="My Rulebook", num_pages=12, toc_entries=toc)

        # Step 1: Register
        source = register_pdf(str(pdf_path), config)
        assert source.source_id == "my-rulebook"
        assert source.page_count == 12

        # Step 2: TOC
        toc_entries = extract_toc("my-rulebook", config)
        assert len(toc_entries) == 9
        assert toc_entries[0].title == "Chapter 1: Introduction"

        # Step 3: Page labels
        labels = extract_page_labels("my-rulebook", config)
        assert len(labels) == 12

        # Step 4: Section tree
        tree = build_section_tree("my-rulebook", config)
        assert len(tree.nodes) == 9
        assert len(tree.root_ids) == 3

        # Check hierarchy
        ch1_id = tree.root_ids[0]
        ch1 = tree.nodes[ch1_id]
        assert "chapter-1-introduction" in ch1_id
        assert ch1.level == 1
        assert len(ch1.children) == 2  # Overview, Getting Started

        overview = tree.nodes[ch1.children[0]]
        assert overview.level == 2
        assert overview.parent_id == ch1.section_id

        # Step 5: Emit skeleton
        manifest = emit_skeleton("my-rulebook", config)
        assert len(manifest) == 9

        # Verify files exist
        output_dir = config.resolved_output_dir()
        for sid, rel_path in manifest.items():
            assert (output_dir / rel_path).exists(), f"Missing: {rel_path}"

        # Verify frontmatter in a file
        some_path = list(manifest.values())[0]
        content = (output_dir / some_path).read_text()
        assert "---" in content
        assert "section_id" in content

    def test_rerun_no_recompute(self, tmp_path: Path, config: WikiConfig):
        """Running the pipeline again should not recompute unchanged steps."""
        pdf_path = tmp_path / "book.pdf"
        toc = [
            [1, "Chapter 1", 1],
            [2, "Section A", 2],
        ]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc)

        # First run
        source = register_pdf(str(pdf_path), config)
        extract_toc("book", config)
        extract_page_labels("book", config)
        build_section_tree("book", config)
        manifest = emit_skeleton("book", config)

        # Check all steps are marked completed
        db = CacheDB(config.resolved_cache_db_path())
        for step in ["register", "toc", "page_labels", "section_tree", "emit_skeleton"]:
            assert db.is_step_completed("book", step), f"Step {step} not marked completed"
        db.close()

        # Second run: should use cache
        source2 = register_pdf(str(pdf_path), config)
        toc2 = extract_toc("book", config)
        labels2 = extract_page_labels("book", config)
        tree2 = build_section_tree("book", config)
        manifest2 = emit_skeleton("book", config)

        # Results should be consistent
        assert source2.sha256 == source.sha256
        assert len(toc2) == 2
        assert len(labels2) == 5
        assert len(tree2.nodes) == len(tree2.nodes)

    def test_force_reruns(self, tmp_path: Path, config: WikiConfig):
        """Using --force should trigger recomputation."""
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc)

        register_pdf(str(pdf_path), config)
        extract_toc("book", config)
        extract_page_labels("book", config)
        build_section_tree("book", config)
        emit_skeleton("book", config)

        # Force re-extract toc
        toc2 = extract_toc("book", config, force=True)
        assert len(toc2) == 1

    def test_artifacts_persisted(self, tmp_path: Path, config: WikiConfig):
        """Check that intermediate artifacts are saved to disk."""
        pdf_path = tmp_path / "book.pdf"
        toc = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc)

        register_pdf(str(pdf_path), config)
        extract_toc("book", config)
        extract_page_labels("book", config)
        build_section_tree("book", config)

        artifacts = ArtifactStore(config.resolved_artifact_dir())
        assert artifacts.has_artifact("book", "pdf_source")
        assert artifacts.has_artifact("book", "toc")
        assert artifacts.has_artifact("book", "page_labels")
        assert artifacts.has_artifact("book", "section_tree")