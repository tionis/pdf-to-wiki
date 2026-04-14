"""Tests for fingerprinting and source_id derivation."""

from __future__ import annotations

from pathlib import Path

from pdf_to_wiki.ingest.fingerprint import compute_sha256, derive_source_id


class TestDeriveSourceId:
    def test_simple_filename(self):
        assert derive_source_id("My_Rulebook.pdf") == "my-rulebook"

    def test_spaces(self):
        assert derive_source_id("Core Rulebook.pdf") == "core-rulebook"

    def test_complex_filename(self):
        assert derive_source_id("PF2e - Core Rulebook (3rd Printing).pdf") == "pf2e-core-rulebook-3rd-printing"

    def test_path_with_directory(self):
        assert derive_source_id("/some/path/to/Book.pdf") == "book"

    def test_no_extension(self):
        assert derive_source_id("manual") == "manual"

    def test_collapsing_hyphens(self):
        assert derive_source_id("A---B___C.pdf") == "a-b-c"

    def test_unicode_normalized(self):
        result = derive_source_id("Ünïcödé Book.pdf")
        # NFKD normalization decomposes unicode; hyphens replace non-ascii
        assert isinstance(result, str)
        assert len(result) > 0


class TestComputeSha256:
    def test_deterministic(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h1 = compute_sha256(f)
        h2 = compute_sha256(f)
        assert h1 == h2
        assert len(h1) == 64  # 256-bit hex

    def test_different_content(self, tmp_path: Path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("aaa")
        f2.write_text("bbb")
        assert compute_sha256(f1) != compute_sha256(f2)