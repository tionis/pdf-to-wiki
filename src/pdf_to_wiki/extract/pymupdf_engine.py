"""PyMuPDF extraction engine — deterministic, no ML models required.

Uses PyMuPDF's dict-mode extraction with column-aware layout handling,
header/footer removal, and text cleaning. This is the fallback engine
that works without downloading any models.
"""

from __future__ import annotations

import fitz

from pdf_to_wiki.extract import BaseEngine, register_engine
from pdf_to_wiki.repair.clean_text import extract_section_text_structured


@register_engine("pymupdf")
class PyMuPDFEngine(BaseEngine):
    """Extraction engine using PyMuPDF with structured layout handling."""

    @property
    def engine_name(self) -> str:
        return "pymupdf_structured"

    @property
    def engine_version(self) -> str:
        return fitz.version[0]

    def extract_page_range(
        self,
        pdf_path: str,
        start_page: int,
        end_page: int,
        start_heading: str | None = None,
    ) -> str:
        """Extract text using PyMuPDF structured extraction.

        Args:
            start_heading: If provided, find this heading on the start page
                and only extract content from that heading onwards.
        """
        doc = fitz.open(pdf_path)
        try:
            text = extract_section_text_structured(
                doc, start_page, end_page, start_heading=start_heading
            )
        finally:
            doc.close()
        return text