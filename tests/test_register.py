"""Tests for PDF registration."""

from __future__ import annotations

from pathlib import Path

from conftest import create_test_pdf

from pdf_to_wiki.cache.db import CacheDB
from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.ingest.register_pdf import register_pdf


class TestRegisterPdf:
    def test_register_new_pdf(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "test-rulebook.pdf"
        sha = create_test_pdf(pdf_path)

        source = register_pdf(str(pdf_path), config)
        assert source.source_id == "test-rulebook"
        assert source.sha256 == sha
        assert source.page_count == 10
        assert source.title == "Test Rulebook"

    def test_register_persists_to_db(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        create_test_pdf(pdf_path)

        register_pdf(str(pdf_path), config)

        db = CacheDB(config.resolved_cache_db_path())
        source = db.get_pdf_source("book")
        assert source is not None
        assert source.page_count == 10
        db.close()

    def test_register_cached_skip(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        create_test_pdf(pdf_path)

        source1 = register_pdf(str(pdf_path), config)
        source2 = register_pdf(str(pdf_path), config)
        assert source1.source_id == source2.source_id

    def test_register_force_reregister(self, tmp_path: Path, config: WikiConfig):
        pdf_path = tmp_path / "book.pdf"
        create_test_pdf(pdf_path)

        register_pdf(str(pdf_path), config)
        source = register_pdf(str(pdf_path), config, force=True)
        assert source.source_id == "book"

    def test_register_missing_pdf(self, tmp_path: Path, config: WikiConfig):
        import pytest
        with pytest.raises(FileNotFoundError):
            register_pdf(str(tmp_path / "nonexistent.pdf"), config)