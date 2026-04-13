"""Marker extraction engine — ML-powered PDF→Markdown conversion.

Uses the marker-pdf library for high-quality text extraction with:
- Multi-column layout awareness
- Table detection and formatting
- Image extraction
- Proper heading hierarchy
- Bold/italic formatting preservation

Marker downloads ML models on first use (~2GB). It processes the
PDF through layout recognition, OCR error detection, and table
recognition pipelines.

Strategy: For best performance, convert the entire PDF in a single
Marker call (models are only loaded once), then split the resulting
Markdown into per-section content by matching section titles to
heading anchors in the Marker output.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import fitz

from rulebook_wiki.extract import BaseEngine, register_engine
from rulebook_wiki.logging import get_logger

logger = get_logger(__name__)

# Lazy singletons — marker is heavy and may not be installed
_marker_converter = None
_model_dict = None


def _get_marker_converter():
    """Lazily initialize Marker converter (loads models on first call)."""
    global _marker_converter, _model_dict

    if _marker_converter is not None:
        return _marker_converter

    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
    except ImportError as e:
        raise ImportError(
            "marker-pdf is not installed. Install it with: pip install marker-pdf"
        ) from e

    logger.info("Initializing Marker models (first run downloads ~2GB)...")
    _model_dict = create_model_dict()
    _marker_converter = PdfConverter(artifact_dict=_model_dict)
    logger.info("Marker models initialized.")
    return _marker_converter


def _get_marker_version() -> str:
    """Get marker version string."""
    try:
        from importlib.metadata import version as pkg_version
        return pkg_version("marker-pdf")
    except Exception:
        return "unknown"


@register_engine("marker")
class MarkerEngine(BaseEngine):
    """Extraction engine using marker-pdf for high-quality conversion."""

    def __init__(self, config) -> None:
        super().__init__(config)
        self._version: str | None = None

    @property
    def engine_name(self) -> str:
        return "marker"

    @property
    def engine_version(self) -> str:
        if self._version is None:
            self._version = _get_marker_version()
        return self._version

    def extract_page_range(
        self,
        pdf_path: str,
        start_page: int,
        end_page: int,
    ) -> str:
        """Extract text using Marker for a page range.

        Creates a temporary PDF with just the needed pages,
        then runs Marker on it and returns the Markdown text.
        """
        from marker.output import text_from_rendered

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Extract pages from source PDF into temp file
            src_doc = fitz.open(pdf_path)
            out_doc = fitz.open()

            actual_end = min(end_page, src_doc.page_count - 1)
            for page_idx in range(start_page, actual_end + 1):
                out_doc.insert_pdf(src_doc, from_page=page_idx, to_page=page_idx)

            out_doc.save(tmp_path)
            out_doc.close()
            src_doc.close()

            # Convert with Marker
            converter = _get_marker_converter()
            rendered = converter(tmp_path)

            # text_from_rendered returns (markdown_text, format, image_dict)
            result = text_from_rendered(rendered)
            if isinstance(result, tuple) and len(result) >= 1:
                markdown_text = result[0]
            else:
                markdown_text = str(result)

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        return markdown_text

    def extract_full_pdf(self, pdf_path: str) -> str:
        """Extract text from the entire PDF in one Marker pass.

        This is the most efficient approach for full-PDF conversion
        since Marker only initializes models once and can leverage
        cross-page context for layout analysis.
        """
        from marker.output import text_from_rendered

        converter = _get_marker_converter()
        rendered = converter(pdf_path)

        # text_from_rendered returns (markdown_text, format, image_dict)
        result = text_from_rendered(rendered)
        if isinstance(result, tuple) and len(result) >= 1:
            return result[0]

        return str(result)


def split_markdown_by_headings(
    markdown: str,
    sections: list[tuple[str, str, int, int]],
) -> dict[str, str]:
    """Split a full-PDF Markdown output into per-section content.

    Given a single Markdown document (from Marker's full-PDF conversion),
    split it into per-section content by matching section titles to
    heading anchors in the Markdown.

    Args:
        markdown: Full Markdown text from Marker.
        sections: List of (section_id, title, start_page, end_page) tuples.

    Returns:
        Dict mapping section_id → extracted Markdown text.
    """
    # Parse heading positions in the Markdown
    lines = markdown.split("\n")
    heading_positions: list[tuple[int, int, str]] = []  # (line_idx, level, title)

    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            heading_positions.append((i, level, title))

    # Build heading ranges (each heading's content spans to the next heading)
    heading_ranges: list[tuple[int, int, int, str]] = []  # (start, end, level, title)
    for j, (pos, level, title) in enumerate(heading_positions):
        if j + 1 < len(heading_positions):
            end_pos = heading_positions[j + 1][0]
        else:
            end_pos = len(lines)
        heading_ranges.append((pos, end_pos, level, title))

    # For each section, find the best matching heading
    result: dict[str, str] = {}

    for section_id, title, _start_page, _end_page in sections:
        # Normalize section title for comparison
        title_clean = _normalize_title(title)

        # Try to match this section to a heading
        matched_idx = None
        best_score = 0

        for j, (_, _, _, heading_title) in enumerate(heading_ranges):
            ht_clean = _normalize_title(heading_title)

            # Exact match
            if ht_clean == title_clean:
                matched_idx = j
                best_score = 100
                break

            # Substring match (section title contained in heading, or vice versa)
            if title_clean and ht_clean:
                if title_clean in ht_clean or ht_clean in title_clean:
                    score = min(len(title_clean), len(ht_clean)) / max(len(title_clean), len(ht_clean)) * 80
                    if score > best_score and len(ht_clean) >= 4:
                        best_score = score
                        matched_idx = j

        if matched_idx is not None and best_score >= 30:
            start, end, _, _ = heading_ranges[matched_idx]
            section_text = "\n".join(lines[start:end]).strip()
            result[section_id] = section_text
        else:
            # No heading match — this section's content isn't identifiable
            # by headings alone. Mark as needing per-page extraction.
            result[section_id] = ""

    return result


def _normalize_title(title: str) -> str:
    """Normalize a heading title for fuzzy matching."""
    # Strip Markdown formatting
    t = re.sub(r"[*_`\[\]():]", "", title)
    # Strip soft hyphens
    t = t.replace("\u00ad", "")
    # Collapse whitespace and lowercase
    t = " ".join(t.split()).lower().strip()
    # Strip trailing punctuation
    t = t.rstrip(".,;:!?")
    return t