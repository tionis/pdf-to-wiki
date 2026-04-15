"""Tests for build-time wiki validation."""

from __future__ import annotations

from pathlib import Path

from conftest import create_test_pdf

from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.emit.markdown_writer import emit_skeleton
from pdf_to_wiki.emit.validate import validate_wiki, ValidationReport
from pdf_to_wiki.ingest.build_section_tree import build_section_tree
from pdf_to_wiki.ingest.extract_page_labels import extract_page_labels
from pdf_to_wiki.ingest.extract_toc import extract_toc
from pdf_to_wiki.ingest.register_pdf import register_pdf


def _run_full_pipeline(pdf_path: str, config: WikiConfig) -> None:
    """Helper: run the full pipeline up to emission."""
    from pdf_to_wiki.ingest.register_pdf import register_pdf as reg
    from pdf_to_wiki.ingest.extract_toc import extract_toc as toc
    from pdf_to_wiki.ingest.extract_page_labels import extract_page_labels as epl
    from pdf_to_wiki.ingest.build_section_tree import build_section_tree as bst

    source = reg(pdf_path, config)
    toc(source.source_id, config)
    epl(source.source_id, config)
    bst(source.source_id, config)


class TestValidation:
    def test_clean_wiki(self, tmp_path: Path, config: WikiConfig):
        """A freshly emitted wiki should validate clean (no broken links)."""
        pdf_path = tmp_path / "book.pdf"
        toc_entries = [
            [1, "Chapter 1", 1],
            [2, "Section A", 1],
            [1, "Chapter 2", 5],
        ]
        create_test_pdf(pdf_path, num_pages=10, toc_entries=toc_entries)
        _run_full_pipeline(str(pdf_path), config)
        emit_skeleton("book", config)

        report = validate_wiki("book", config)
        assert report.total_files > 0
        assert report.broken_links == []
        assert report.broken_images == []

    def test_broken_link_detected(self, tmp_path: Path, config: WikiConfig):
        """A manually added broken link should be detected."""
        pdf_path = tmp_path / "book.pdf"
        toc_entries = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc_entries)
        _run_full_pipeline(str(pdf_path), config)
        emit_skeleton("book", config)

        # Inject a broken link into a file
        output_dir = config.resolved_output_dir()
        md_files = list(output_dir.rglob("*.md"))
        if md_files:
            content = md_files[0].read_text()
            content += "\n\nSee [Missing Page](../nonexistent.md)\n"
            md_files[0].write_text(content)

            report = validate_wiki("book", config)
            assert len(report.broken_links) >= 1

    def test_orphan_file_detected(self, tmp_path: Path, config: WikiConfig):
        """An orphan .md file should be detected."""
        pdf_path = tmp_path / "book.pdf"
        toc_entries = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc_entries)
        _run_full_pipeline(str(pdf_path), config)
        emit_skeleton("book", config)

        # Create an orphan file
        output_dir = config.resolved_output_dir()
        orphan_path = output_dir / config.books_dir / "book" / "orphan.md"
        orphan_path.parent.mkdir(parents=True, exist_ok=True)
        orphan_path.write_text("# Orphan\n\nThis file is not in the manifest.")

        report = validate_wiki("book", config)
        assert len(report.orphan_files) >= 1

    def test_unresolved_page_ref_detected(self, tmp_path: Path, config: WikiConfig):
        """An unresolved {{page-ref:N}} should be detected."""
        pdf_path = tmp_path / "book.pdf"
        toc_entries = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc_entries)
        _run_full_pipeline(str(pdf_path), config)
        emit_skeleton("book", config)

        # Inject an unresolved page ref
        output_dir = config.resolved_output_dir()
        md_files = list(output_dir.rglob("*.md"))
        if md_files:
            content = md_files[0].read_text()
            content += "\n\nSee {{page-ref:999}} for details.\n"
            md_files[0].write_text(content)

            report = validate_wiki("book", config)
            assert len(report.unresolved_page_refs) >= 1

    def test_missing_image_detected(self, tmp_path: Path, config: WikiConfig):
        """A broken image reference should be detected."""
        pdf_path = tmp_path / "book.pdf"
        toc_entries = [[1, "Chapter 1", 1]]
        create_test_pdf(pdf_path, num_pages=5, toc_entries=toc_entries)
        _run_full_pipeline(str(pdf_path), config)
        emit_skeleton("book", config)

        # Inject a broken image reference
        output_dir = config.resolved_output_dir()
        md_files = list(output_dir.rglob("*.md"))
        if md_files:
            content = md_files[0].read_text()
            content += "\n\n![](../.assets/nonexistent.png)\n"
            md_files[0].write_text(content)

            report = validate_wiki("book", config)
            assert len(report.broken_images) >= 1

    def test_validation_report_summary(self, tmp_path: Path, config: WikiConfig):
        """The summary should format correctly."""
        report = ValidationReport(source_id="test")
        report.total_files = 10
        summary = report.summary()
        assert "test" in summary
        assert "10" in summary
        assert "✅ No issues found" in summary