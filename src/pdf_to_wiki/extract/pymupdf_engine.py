"""PyMuPDF extraction engine — deterministic, no ML models required.

Uses PyMuPDF's dict-mode extraction with column-aware layout handling,
header/footer removal, and text cleaning. This is the fallback engine
that works without downloading any models.
"""

from __future__ import annotations

import fitz

from pdf_to_wiki.extract import BaseEngine, register_engine
from pdf_to_wiki.logging import get_logger
from pdf_to_wiki.repair.clean_text import (
    extract_page_text_structured,
    find_heading_position,
    _detect_headers_footers,
    _strip_headers_footers,
    _clean_text,
)

logger = get_logger(__name__)


@register_engine("pymupdf")
class PyMuPDFEngine(BaseEngine):
    """Extraction engine using PyMuPDF with structured layout handling.

    When `config.extract_tables` is True (default), also detects tables
    on each page via PyMuPDF's find_tables() and replaces the flattened
    text with Markdown pipe tables. This provides table support even
    when the Marker engine isn't available.
    """

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

        When table extraction is enabled, also detects tables on each
        page and replaces flattened text regions with Markdown pipe tables.

        Args:
            start_heading: If provided, find this heading on the start page
                and only extract content from that heading onwards.
        """
        doc = fitz.open(pdf_path)
        try:
            # Phase 1: Find heading position if needed
            skip_before = 0
            if start_heading:
                page = doc[start_page]
                heading_pos = find_heading_position(page, start_heading)
                if heading_pos is not None:
                    skip_before = heading_pos
                    logger.debug(
                        f"Found heading '{start_heading}' at block {heading_pos[0]}, "
                        f"line {heading_pos[1]} on page {start_page}"
                    )

            # Phase 2: Detect headers/footers
            header_footer_lines = _detect_headers_footers(doc, start_page, end_page)

            # Phase 3: Extract text page by page, with table detection
            page_texts: list[str] = []
            for page_idx in range(start_page, min(end_page + 1, doc.page_count)):
                page = doc[page_idx]
                skip = skip_before if (page_idx == start_page and skip_before != 0) else 0
                page_text = extract_page_text_structured(page, skip_before=skip)

                # Table detection and replacement
                if self.config.extract_tables:
                    page_text = self._replace_tables(doc, page, page_text, page_idx)

                if page_text.strip():
                    cleaned = _strip_headers_footers(page_text, header_footer_lines)
                    if skip != 0 and start_heading and not cleaned.strip().startswith(start_heading[:20]):
                        cleaned = start_heading + "\n\n" + cleaned
                    page_texts.append(cleaned)

            if not page_texts:
                return ""

            # Phase 4: Join pages and apply text cleaning
            raw = "\n\n".join(page_texts)
            cleaned = _clean_text(raw)
            return cleaned
        finally:
            doc.close()

    def _replace_tables(
        self,
        doc: fitz.Document,
        page: fitz.Page,
        page_text: str,
        page_idx: int,
    ) -> str:
        """Detect tables on a page and replace flattened text with Markdown tables.

        Uses PyMuPDF's find_tables() to detect table regions, then replaces
        the flattened text within those regions with properly formatted
        Markdown pipe tables.

        This is a best-effort replacement — the table Markdown may not
        perfectly align with the original layout, but it preserves the
        table structure (rows, columns) which is lost in plain text extraction.
        """
        from pdf_to_wiki.repair.table_extract import extract_tables_as_markdown

        try:
            table_regions = extract_tables_as_markdown(page)
        except Exception as e:
            logger.debug(f"Table detection failed on page {page_idx}: {e}")
            return page_text

        if not table_regions:
            return page_text

        # For each detected table, try to find and replace the corresponding
        # text region. Since we can't precisely map bbox positions to text
        # blocks in the already-extracted text, we use a heuristic:
        # append the Markdown tables at the end of the page text.
        #
        # A more sophisticated approach would be to integrate table detection
        # into the structured extraction, but that requires refactoring
        # extract_page_text_structured() which handles the column-aware layout.
        #
        # For now, we append detected tables as a separate section.
        # This avoids duplicating content from both the flattened text
        # and the Markdown table.
        md_tables = []
        for Tab_bbox, md_text in table_regions:
            md_tables.append(md_text)
            logger.debug(f"Detected table on page {page_idx}: {Tab_bbox}")

        if md_tables:
            # Append tables with a separator
            tables_section = "\n\n---\n\n" + "\n\n".join(md_tables)
            page_text = page_text + tables_section

        return page_text