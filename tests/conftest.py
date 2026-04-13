"""Shared test fixtures and helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test outputs."""
    return tmp_path


@pytest.fixture
def config(tmp_path: Path):
    """Provide a WikiConfig pointing at temporary directories."""
    from rulebook_wiki.config import WikiConfig

    cfg = WikiConfig(
        output_dir=str(tmp_path / "outputs" / "wiki"),
        books_dir="books",
        cache_db_path=str(tmp_path / "cache" / "cache.db"),
        artifact_dir=str(tmp_path / "artifacts"),
    )
    return cfg


def create_test_pdf(
    path: Path,
    title: str = "Test Rulebook",
    num_pages: int = 10,
    toc_entries: list[tuple[int, str, int]] | None = None,
    page_labels: bool = False,
) -> str:
    """Create a small test PDF with optional TOC and page labels.

    Args:
        path: output path for the PDF
        title: PDF metadata title
        num_pages: number of pages to create
        toc_entries: list of (level, title, 1-based-page) for bookmarks
        page_labels: whether to add Roman-numeral front matter labels

    Returns:
        SHA-256 of the created file
    """
    import fitz

    doc = fitz.open()
    doc.set_metadata({"title": title})

    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1}")

    # Add bookmarks/TOC
    if toc_entries:
        # fitz.set_toc expects [[level, title, page_1based], ...]
        doc.set_toc(toc_entries)

    # Add page labels if requested
    if page_labels:
        # Use fitz's page label setting
        # Roman numerals for first 4 pages, Arabic starting from 1 for rest
        doc.set_page_labels(4, "roman")  # first 4 pages get Roman labels

    doc.save(str(path))
    doc.close()

    # Compute sha256
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()