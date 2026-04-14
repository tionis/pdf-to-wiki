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

from pdf_to_wiki.extract import BaseEngine, register_engine
from pdf_to_wiki.logging import get_logger

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
            "marker-pdf is not installed. Install it with: uv add marker-pdf (or pip install marker-pdf)"
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

    def extract_full_pdf_with_images(self, pdf_path: str) -> tuple[str, dict]:
        """Extract text and images from the entire PDF in one Marker pass.

        Returns:
            Tuple of (markdown_text, images_dict) where images_dict maps
            filenames to PIL Image objects.
        """
        from marker.output import text_from_rendered

        converter = _get_marker_converter()
        rendered = converter(pdf_path)

        result = text_from_rendered(rendered)
        if isinstance(result, tuple) and len(result) >= 3:
            markdown_text, fmt, images_dict = result
            return markdown_text, images_dict
        elif isinstance(result, tuple) and len(result) >= 1:
            return result[0], {}

        return str(result), {}


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

    # Merge consecutive headings with the same normalized title.
    # Marker sometimes emits the same heading twice: once for a table,
    # once for body text. Merging keeps both together.
    merged_ranges: list[tuple[int, int, int, str]] = []
    for pos, end, level, title in heading_ranges:
        if merged_ranges:
            prev_pos, prev_end, prev_level, prev_title = merged_ranges[-1]
            if _normalize_title(title) == _normalize_title(prev_title) and level == prev_level:
                # Merge: extend previous range to cover this one too
                merged_ranges[-1] = (prev_pos, end, prev_level, prev_title)
                continue
        merged_ranges.append((pos, end, level, title))
    heading_ranges = merged_ranges

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
            # No heading match — fall back to page-range extraction.
            # Use Marker's <span id="page-X-Y"> anchors to find
            # the text for this section's page range.
            page_text = _extract_by_page_range(markdown, _start_page, _end_page)
            result[section_id] = page_text

    return result


def _extract_by_page_range(markdown: str, start_page: int, end_page: int) -> str:
    """Extract text from Marker's Markdown by page-range anchors.

    Marker inserts <span id="page-X-Y"></span> anchors at the start
    of each page. This function finds the anchors for pages start_page
    through end_page and returns the text between them.

    Pages are 0-indexed (matching PyMuPDF's convention).
    """
    # Find all page anchors and their line positions
    page_anchors: list[tuple[int, int]] = []  # (line_idx, page_num)
    for i, line in enumerate(markdown.split("\n")):
        m = re.match(r'<span\s+id="page-(\d+)-\d+"\s*>\s*</span>', line)
        if m:
            page_num = int(m.group(1))
            page_anchors.append((i, page_num))

    if not page_anchors:
        return ""

    lines = markdown.split("\n")

    # Find the start anchor (first page >= start_page)
    start_line = None
    for line_idx, page_num in page_anchors:
        if page_num >= start_page:
            start_line = line_idx
            break

    # Find the end anchor (first page > end_page)
    end_line = None
    for line_idx, page_num in page_anchors:
        if page_num > end_page:
            end_line = line_idx
            break

    if start_line is None:
        return ""

    if end_line is None:
        # No more pages after end_page — go to end of document
        end_line = len(lines)

    section_lines = lines[start_line:end_line]
    text = "\n".join(section_lines).strip()

    # Remove the trailing page anchor if present
    text = re.sub(r'\s*<span\s+id="page-\d+-\d+"\s*>\s*</span>\s*$', "", text, flags=re.MULTILINE)

    return text


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


def save_images(
    images_dict: dict,
    source_id: str,
    output_dir: Path,
) -> dict[str, str]:
    """Save Marker's extracted images to the wiki assets directory.

    Args:
        images_dict: Dict mapping filenames (e.g., '_page_0_Picture_0.jpeg')
            to PIL Image objects, as returned by Marker.
        source_id: The PDF source ID for namespacing.
        output_dir: The wiki output directory (e.g., data/outputs/wiki/).

    Returns:
        Dict mapping original filename to the relative path where the
        image was saved (e.g., 'assets/storypath/page_0_picture_0.png').
    """
    if not images_dict:
        return {}

    assets_dir = output_dir / "assets" / source_id
    assets_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, str] = {}

    for original_name, img in images_dict.items():
        # Clean the filename: remove leading underscore, normalize
        clean_name = original_name.lstrip("_")
        # Save as PNG for lossless quality (PIL handles the conversion)
        base_name = Path(clean_name).stem + ".png"
        save_path = assets_dir / base_name

        try:
            img.save(str(save_path), "PNG")
            # Relative path from the wiki root for use in Markdown
            rel_path = f"assets/{source_id}/{base_name}"
            saved[original_name] = rel_path
            logger.debug(f"Saved image: {save_path}")
        except Exception as e:
            logger.warning(f"Failed to save image {original_name}: {e}")

    logger.info(f"Saved {len(saved)} images to {assets_dir}")
    return saved


def rewrite_image_refs(
    markdown: str,
    image_map: dict[str, str],
    source_id: str,
    output_dir: Path,
) -> str:
    """Rewrite Markdown image references to point to saved image files.

    Converts references like ![](_page_0_Picture_0.jpeg) to
    ![](../assets/source_id/page_0_picture_0.png) with paths
    relative to the note's location in the wiki.

    Args:
        markdown: The Markdown text containing image references.
        image_map: Dict mapping original filename to relative path from wiki root.
        source_id: The PDF source ID.
        output_dir: The wiki output directory.

    Returns:
        Markdown text with rewritten image references.
    """
    if not image_map:
        return markdown

    # Pattern: ![alt](filename) or ![](filename)
    def _replace_img(m):
        alt_text = m.group(1) or ""
        original_ref = m.group(2)

        if original_ref in image_map:
            new_path = image_map[original_ref]
            return f"![{alt_text}]({new_path})"

        # Try matching just the filename part
        ref_basename = original_ref.lstrip("_")
        for orig_key, new_path in image_map.items():
            orig_basename = orig_key.lstrip("_")
            if orig_basename == ref_basename:
                return f"![{alt_text}]({new_path})"

        # No match — leave as-is
        return m.group(0)

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _replace_img, markdown)