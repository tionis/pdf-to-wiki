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
    max_absorb_depth: int = 3,
) -> dict[str, str]:
    """Split a full-PDF Markdown output into per-section content.

    Given a single Markdown document (from Marker's full-PDF conversion),
    split it into per-section content by matching section titles to
    heading anchors in the Markdown.

    Args:
        markdown: Full Markdown text from Marker.
        sections: List of (section_id, title, start_page, end_page) tuples.
        max_absorb_depth: Maximum heading level difference for absorbing
            unclaimed sub-headings into a matched section. E.g., if the
            matched heading is level 2 and max_absorb_depth=3, headings
            up to level 5 will be absorbed. Default 3 is permissive;
            set to 1 for strict same-level-only absorption.

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

    # Pass 1: For each section, find the best matching heading range.
    # Build a set of heading-range indices that are claimed by sections.
    section_matches: dict[str, int] = {}  # section_id → heading_range index
    heading_claimed: set[int] = set()  # indices of heading_ranges claimed by sections

    # Track unclaimed headings for page-proximity fuzzy matching
    unmatched_sections: list[tuple[str, str, int, int]] = []  # sections not yet matched

    for section_id, title, start_page, end_page in sections:
        title_clean = _normalize_title(title)
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
            section_matches[section_id] = matched_idx
            heading_claimed.add(matched_idx)
        else:
            unmatched_sections.append((section_id, title, start_page, end_page))

    # Pass 1b: Fuzzy matching for unmatched sections.
    # When exact/substring matching fails, try fuzzy matching using:
    # 1. Token-level Jaccard similarity (word overlap)
    # 2. Page-proximity bonus (heading on/near the section's start page)
    # 3. Prefix/suffix stripping ("The", "Chapter", section numbers)
    if unmatched_sections:
        # Build a map of heading_range index → approximate page number
        # (estimated from page anchors in the markdown text)
        heading_pages = _estimate_heading_pages(lines, heading_ranges)

        for section_id, title, start_page, end_page in unmatched_sections:
            title_clean = _normalize_title(title)
            title_tokens = set(title_clean.split())
            matched_idx = None
            best_score = 0

            for j, (_, _, _, heading_title) in enumerate(heading_ranges):
                if j in heading_claimed:
                    continue  # Already claimed by exact/substring match

                ht_clean = _normalize_title(heading_title)
                ht_tokens = set(ht_clean.split())

                # Token-level Jaccard similarity
                if title_tokens and ht_tokens:
                    intersection = title_tokens & ht_tokens
                    union = title_tokens | ht_tokens
                    jaccard = len(intersection) / len(union) if union else 0
                else:
                    jaccard = 0

                # Also try stripped versions (remove common prefixes/suffixes)
                title_stripped = _strip_heading_affixes(title_clean)
                ht_stripped = _strip_heading_affixes(ht_clean)
                if title_stripped and ht_stripped:
                    st_tokens = set(title_stripped.split())
                    sh_tokens = set(ht_stripped.split())
                    if st_tokens and sh_tokens:
                        s_intersection = st_tokens & sh_tokens
                        s_union = st_tokens | sh_tokens
                        stripped_jaccard = len(s_intersection) / len(s_union) if s_union else 0
                        jaccard = max(jaccard, stripped_jaccard)

                if jaccard < 0.3:
                    continue  # Too different to consider

                # Page-proximity bonus: if the heading is on or near
                # the section's start page, boost the score
                page_bonus = 0.0
                if j in heading_pages:
                    page_dist = abs(heading_pages[j] - start_page)
                    if page_dist == 0:
                        page_bonus = 0.3
                    elif page_dist <= 1:
                        page_bonus = 0.2
                    elif page_dist <= 2:
                        page_bonus = 0.1

                score = jaccard + page_bonus

                if score > best_score:
                    best_score = score
                    matched_idx = j

            # Require a minimum fuzzy score of 0.5
            if matched_idx is not None and best_score >= 0.5:
                section_matches[section_id] = matched_idx
                heading_claimed.add(matched_idx)

    # Pass 2: For each matched section, absorb subsequent unclaimed
    # heading ranges. Marker often creates sub-headings (e.g. "Ranged
    # Weapons Chart" inside "Weapons") that aren't in the TOC but contain
    # important content like tables. We extend the section's end to cover
    # all consecutive unclaimed heading ranges until we hit one claimed
    # by another section.
    #
    # The max_absorb_depth parameter limits how deep sub-headings can be
    # relative to the matched heading. E.g., if the matched heading is
    # level 2 and max_absorb_depth=3, only headings at level 3-5 are
    # absorbed. A heading at level 1 (deeper than the parent) would not
    # be absorbed, preventing a pathological document from pulling in
    # an entire chapter.
    section_end_idx: dict[str, int] = {}  # section_id → last heading_range index
    for section_id, match_idx in section_matches.items():
        end_idx = match_idx
        matched_level = heading_ranges[match_idx][2]
        # Look ahead at subsequent heading ranges
        for j in range(match_idx + 1, len(heading_ranges)):
            if j in heading_claimed:
                # This heading is claimed by another section — stop
                break
            # Check depth limit: only absorb if the heading is deep enough
            # relative to the matched heading
            sub_level = heading_ranges[j][2]
            if (sub_level - matched_level) > max_absorb_depth:
                # Too deep — stop absorbing. This heading likely starts
                # a new major section that just happens to be unclaimed.
                break
            # Unclaimed heading within depth limit — absorb it
            end_idx = j
        section_end_idx[section_id] = end_idx

    # Pass 3: Assemble the section text from the heading ranges
    result: dict[str, str] = {}

    for section_id, title, _start_page, _end_page in sections:
        if section_id in section_matches:
            match_idx = section_matches[section_id]
            end_idx = section_end_idx[section_id]
            start = heading_ranges[match_idx][0]
            end = heading_ranges[end_idx][1]  # end of the last absorbed range
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


# Common heading prefixes/suffixes to strip for fuzzy matching
# These are words commonly added by markers but not in the TOC
_STRIP_PREFIXES = {"the", "a", "an", "chapter", "ch", "section", "part", "book", "appendix"}
_STRIP_SUFFIXES = {"cont", "contd", "continued", "(cont)", "(continued)"}


def _strip_heading_affixes(title: str) -> str:
    """Strip common heading prefixes and suffixes for fuzzy matching.

    Removes article words (the, a, an), chapter/section labels, and
    continuation markers that often cause mismatches between the TOC
    and Marker's emitted headings.
    """
    tokens = title.split()
    if not tokens:
        return title

    # Strip prefixes
    while tokens and tokens[0] in _STRIP_PREFIXES:
        remaining = tokens[1:]
        if not remaining:
            break  # Don't strip if it would leave nothing
        tokens = remaining

    # Strip suffixes
    while tokens and tokens[-1] in _STRIP_SUFFIXES:
        tokens = tokens[:-1]

    # Also strip numeric prefixes like "1.", "2.", etc.
    if tokens and re.match(r"^\d+\.?", tokens[0]):
        tokens[0] = re.sub(r"^\d+\.?\s*", "", tokens[0])
        if not tokens[0]:
            tokens = tokens[1:]

    return " ".join(tokens)


def _estimate_heading_pages(
    lines: list[str],
    heading_ranges: list[tuple[int, int, int, str]],
) -> dict[int, int]:
    """Estimate the PDF page number for each heading range.

    Uses Marker's <span id="page-N-M"> anchors to map line positions
    to page numbers. Each heading range's page is estimated as the
    page of the first anchor at or before the heading's start line.

    Returns:
        Dict mapping heading_range index → estimated 0-based page number.
    """
    # Build map of line → page number from page anchors
    anchor_pages: list[tuple[int, int]] = []  # (line_idx, page_num)
    for i, line in enumerate(lines):
        m = re.match(r'<span\s+id="page-(\d+)-\d+"\s*>\s*</span>', line)
        if m:
            anchor_pages.append((i, int(m.group(1))))

    if not anchor_pages:
        return {}

    result: dict[int, int] = {}
    for j, (start_line, _end, _level, _title) in enumerate(heading_ranges):
        # Find the last anchor before or at start_line
        page = 0
        for anchor_line, anchor_page in anchor_pages:
            if anchor_line <= start_line:
                page = anchor_page
            else:
                break
        result[j] = page

    return result


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