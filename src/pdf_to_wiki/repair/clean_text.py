"""Structured text extraction and cleaning from PDF pages.

Uses PyMuPDF's dict-mode text extraction to get position data,
then applies deterministic cleaning:

1. Column-aware reading order (left column, then right column)
2. Header/footer detection and removal (text repeated at consistent
   y-positions across pages)
3. Soft-hyphen de-breaking (rejoin words split across lines)
4. Hard-hyphen line-break rejoining
5. Paragraph reassembly (merge short lines into proper paragraphs)
6. Page number and running-header stripping
7. Whitespace normalization

This module is the extraction engine. The caching/step orchestration
lives in ingest/extract_text.py which delegates here.
"""

from __future__ import annotations

import re
from collections import Counter

import fitz  # PyMuPDF

from pdf_to_wiki.logging import get_logger

logger = get_logger(__name__)

# Soft hyphen character (U+00AD) used by PyMuPDF for word breaks.
# This is the character that appears inline in PDF text to mark
# word-break opportunities. Removing it joins word fragments.
# Note: \xad and \u00ad are the same character (ord 173).
SOFT_HYPHEN = "\u00ad"

# Known dingbats/symbol font mappings.
# These fonts use standard ASCII codes for decorative characters.
# PyMuPDF extracts the character code, not the visual glyph.
# We map these to their visual equivalents so the text reads correctly.
DINGBATS_FONT_MAP: dict[str, dict[str, str]] = {
    "FantasyRPGDings": {
        "Y": "\u2022",  # Bullet dot (•) — used for dot ratings in Storypath games
    },
    # Common ZapfDingbats mappings (partial)
    "ZapfDingbats": {
        "l": "\u25cf",  # Filled circle (●)
        "m": "\u25a0",  # Filled square (■)
        "n": "\u25b2",  # Up triangle (▲)
        "q": "\u2665",  # Heart (♥)
    },
    "Symbol": {
        "b": "\u222b",  # Integral (∫)
        "p": "\u03c0",  # Pi (π)
        "S": "\u03a3",  # Sigma (Σ)
    },
}


def find_heading_position(page: fitz.Page, heading_title: str) -> tuple[int, int] | None:
    """Find the block and line index of a heading on a page by font size.

    Returns (block_index_in_reading_order, line_index_within_block) or None.
    Uses font size to identify the real heading, not a running header.

    This correctly handles two-column layouts by sorting blocks in
    reading order (left column first, then right column).
    """
    data = page.get_text("dict")
    page_width = page.rect.width

    font_sizes = []
    for block in data.get("blocks", []):
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if span["text"].strip():
                    font_sizes.append(span["size"])

    if not font_sizes:
        return None

    font_size_counts = Counter(font_sizes)
    body_size = font_size_counts.most_common(1)[0][0]
    heading_threshold = body_size * 1.3

    # Collect all text blocks in reading order (same logic as extract_page_text_structured)
    text_blocks = []
    for block in data.get("blocks", []):
        if "lines" not in block:
            continue
        bbox = block["bbox"]
        x0, y0 = bbox[0], bbox[1]
        block_text = _extract_block_text(block)
        if block_text.strip():
            text_blocks.append({
                "x0": x0, "y0": y0,
                "text": block_text,
                "block": block,
            })

    left_blocks = [b for b in text_blocks if b["x0"] < page_width * 0.45]
    right_blocks = [b for b in text_blocks if b["x0"] >= page_width * 0.45]

    if left_blocks and right_blocks and len(right_blocks) >= 3:
        left_blocks.sort(key=lambda b: (b["y0"], b["x0"]))
        right_blocks.sort(key=lambda b: (b["y0"], b["x0"]))
        ordered_blocks = left_blocks + right_blocks
    else:
        ordered_blocks = sorted(text_blocks, key=lambda b: (b["y0"], b["x0"]))

    escaped = re.escape(heading_title)
    for blk_idx, block_info in enumerate(ordered_blocks):
        block_data = block_info["block"]
        for ln_idx, line in enumerate(block_data["lines"]):
            line_text = "".join(span["text"] for span in line["spans"]).strip()
            max_size = max(
                (span["size"] for span in line["spans"] if span["text"].strip()),
                default=0,
            )
            if re.fullmatch(
                rf"#{{0,3}}\s*\*{{0,2}}{escaped}\*{{0,2}}\s*",
                line_text,
                re.IGNORECASE,
            ) and max_size >= heading_threshold:
                return (blk_idx, ln_idx)

    return None


def extract_page_text_structured(page: fitz.Page, skip_before: int | tuple[int, int] = 0) -> str:
    """Extract text from a single PDF page with column-aware layout handling.

    Uses PyMuPDF's dict mode to get text blocks with position data,
    then sorts them in reading order (left column top-to-bottom,
    then right column top-to-bottom) and applies text cleaning.

    Args:
        skip_before: If an int, skip this many blocks from the start of
            reading order. If a tuple (block_idx, line_idx), skip blocks
            before block_idx and lines before line_idx within that block.
    """
    data = page.get_text("dict")

    text_blocks = []
    for block in data.get("blocks", []):
        if "lines" not in block:
            continue  # Skip images

        bbox = block["bbox"]
        x0, y0, x1, y1 = bbox
        block_text = _extract_block_text(block)

        if block_text.strip():
            text_blocks.append({
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "text": block_text,
                "block": block,  # Keep reference for line-level splitting
            })

    if not text_blocks:
        return ""

    page_width = page.rect.width

    left_blocks = [b for b in text_blocks if b["x0"] < page_width * 0.45]
    right_blocks = [b for b in text_blocks if b["x0"] >= page_width * 0.45]

    if left_blocks and right_blocks and len(right_blocks) >= 3:
        left_blocks.sort(key=lambda b: (b["y0"], b["x0"]))
        right_blocks.sort(key=lambda b: (b["y0"], b["x0"]))
        ordered_blocks = left_blocks + right_blocks
    else:
        ordered_blocks = sorted(text_blocks, key=lambda b: (b["y0"], b["x0"]))

    # Skip blocks before the heading in reading order
    if isinstance(skip_before, int) and skip_before > 0:
        ordered_blocks = ordered_blocks[skip_before:]
    elif isinstance(skip_before, tuple):
        blk_skip, ln_skip = skip_before
        # Skip whole blocks before blk_skip
        remaining = []
        for i, b in enumerate(ordered_blocks):
            if i < blk_skip:
                continue
            elif i == blk_skip:
                # For the heading block, extract only from line ln_skip onwards
                block_data = b.get("block", b)
                if "lines" in block_data:
                    lines_text = []
                    for j, line in enumerate(block_data["lines"]):
                        if j < ln_skip:
                            continue
                        spans_text = []
                        for span in line["spans"]:
                            text = span["text"]
                            font = span.get("font", "")
                            if font in DINGBATS_FONT_MAP:
                                mapping = DINGBATS_FONT_MAP[font]
                                text = "".join(mapping.get(ch, ch) for ch in text)
                            spans_text.append(text)
                        line_text = " ".join(spans_text).strip()
                        if line_text:
                            lines_text.append(line_text)
                    if lines_text:
                        remaining.append("\n".join(lines_text))
            else:
                remaining.append(b["text"])
        # Join remaining parts with double newlines
        page_text = "\n\n".join(remaining)
        return page_text

    # Join blocks with double newlines (paragraph breaks)
    page_text = "\n\n".join(b["text"] for b in ordered_blocks)
    return page_text


def extract_page_text_with_blocks(
    page: fitz.Page, skip_before: int | tuple[int, int] = 0
) -> tuple[str, list[dict]]:
    """Extract text from a page and return both the text and the ordered blocks.

    Same as extract_page_text_structured() but also returns the ordered
    block list with bounding box data. This is used by the PyMuPDF engine
    for in-place table replacement.

    Returns:
        Tuple of (page_text, ordered_blocks) where each block has
        x0, y0, x1, y1, text fields.
    """
    data = page.get_text("dict")

    text_blocks = []
    for block in data.get("blocks", []):
        if "lines" not in block:
            continue

        bbox = block["bbox"]
        x0, y0, x1, y1 = bbox
        block_text = _extract_block_text(block)

        if block_text.strip():
            text_blocks.append({
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "text": block_text,
                "block": block,
            })

    if not text_blocks:
        return "", []

    page_width = page.rect.width

    left_blocks = [b for b in text_blocks if b["x0"] < page_width * 0.45]
    right_blocks = [b for b in text_blocks if b["x0"] >= page_width * 0.45]

    if left_blocks and right_blocks and len(right_blocks) >= 3:
        left_blocks.sort(key=lambda b: (b["y0"], b["x0"]))
        right_blocks.sort(key=lambda b: (b["y0"], b["x0"]))
        ordered_blocks = left_blocks + right_blocks
    else:
        ordered_blocks = sorted(text_blocks, key=lambda b: (b["y0"], b["x0"]))

    # Apply skip_before if specified
    if isinstance(skip_before, int) and skip_before > 0:
        ordered_blocks = ordered_blocks[skip_before:]
    elif isinstance(skip_before, tuple):
        blk_skip, ln_skip = skip_before
        remaining_blocks = []
        for i, b in enumerate(ordered_blocks):
            if i < blk_skip:
                continue
            elif i == blk_skip:
                # For the heading block, extract only from line ln_skip onwards
                block_data = b.get("block", b)
                if "lines" in block_data:
                    lines_text = []
                    for j, line in enumerate(block_data["lines"]):
                        if j < ln_skip:
                            continue
                        spans_text = []
                        for span in line["spans"]:
                            text = span["text"]
                            font = span.get("font", "")
                            if font in DINGBATS_FONT_MAP:
                                mapping = DINGBATS_FONT_MAP[font]
                                text = "".join(mapping.get(ch, ch) for ch in text)
                            spans_text.append(text)
                        line_text = " ".join(spans_text).strip()
                        if line_text:
                            lines_text.append(line_text)
                    if lines_text:
                        remaining_blocks.append({**b, "text": "\n".join(lines_text)})
            else:
                remaining_blocks.append(b)
        ordered_blocks = remaining_blocks

    page_text = "\n\n".join(b["text"] for b in ordered_blocks)
    return page_text, ordered_blocks


def extract_page_text_simple(page: fitz.Page) -> str:
    """Simple fallback extraction using PyMuPDF's text mode."""
    return page.get_text("text")


def extract_section_text_structured(
    doc: fitz.Document,
    start_page: int,
    end_page: int,
    start_heading: str | None = None,
) -> str:
    """Extract text for a section using structured extraction.

    Uses column-aware reading order, header/footer removal,
    and text cleaning.

    Args:
        start_heading: If provided, find this heading on the start page
            and only extract content from that heading onwards. Uses
            font-size detection to find the real heading (not a running
            header) and then skips blocks before it in reading order.
    """
    # Phase 1: For the start page, find the heading block/line index
    # if start_heading is specified.
    skip_before = 0
    if start_heading:
        page = doc[start_page]
        heading_pos = find_heading_position(page, start_heading)
        if heading_pos is not None:
            skip_before = heading_pos  # (block_idx, line_idx) tuple
            logger.debug(
                f"Found heading '{start_heading}' at block {heading_pos[0]}, "
                f"line {heading_pos[1]} on page {start_page} — will skip preceding content"
            )
        else:
            logger.debug(
                f"Heading '{start_heading}' not found on page {start_page}, "
                f"extracting full page"
            )

    # Phase 2: Collect header/footer candidates
    header_footer_lines = _detect_headers_footers(doc, start_page, end_page)

    # Phase 3: Extract text page by page
    page_texts: list[str] = []
    for page_idx in range(start_page, min(end_page + 1, doc.page_count)):
        page = doc[page_idx]
        # On the start page, skip content before the heading
        skip = skip_before if (page_idx == start_page and skip_before != 0) else 0
        page_text = extract_page_text_structured(page, skip_before=skip)
        if page_text.strip():
            cleaned = _strip_headers_footers(page_text, header_footer_lines)
            # When skip_before is set, the first paragraph IS the section heading.
            # Header/footer removal may strip it if it's also used as a running
            # header. Re-add it if it was stripped.
            if skip != 0 and start_heading and not cleaned.strip().startswith(start_heading[:20]):
                cleaned = start_heading + "\n\n" + cleaned
            page_texts.append(cleaned)

    if not page_texts:
        return ""

    # Phase 4: Join pages and apply text cleaning
    raw = "\n\n".join(page_texts)
    cleaned = _clean_text(raw)
    return cleaned


def _extract_block_text(block: dict) -> str:
    """Extract text from a dict-mode block, preserving line structure.

    Applies dingbats font mapping so that symbol characters
    (e.g., Y in FantasyRPGDings → •) are rendered correctly.
    """
    lines: list[str] = []
    for line in block.get("lines", []):
        spans_text: list[str] = []
        for span in line.get("spans", []):
            text = span["text"]
            font = span.get("font", "")
            # Apply dingbats font mapping
            if font in DINGBATS_FONT_MAP:
                mapping = DINGBATS_FONT_MAP[font]
                text = "".join(mapping.get(ch, ch) for ch in text)
            spans_text.append(text)
        lines.append(" ".join(spans_text))

    # Join lines within a block with single newlines
    return "\n".join(lines)


def _detect_headers_footers(
    doc: fitz.Document,
    start_page: int,
    end_page: int,
    min_occurrences: int = 2,
) -> set[str]:
    """Detect repeating header/footer text across pages.

    A line is considered a header/footer if it appears verbatim
    on at least min_occurrences pages at a consistent y-position.
    """
    line_positions: dict[str, list[tuple[float, float]]] = {}

    # Sample up to 20 pages to detect headers/footers
    sample_pages = range(start_page, min(end_page + 1, start_page + 20))

    for page_idx in sample_pages:
        if page_idx >= doc.page_count:
            break
        page = doc[page_idx]
        data = page.get_text("dict")

        for block in data.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block.get("lines", []):
                text = " ".join(span["text"] for span in line.get("spans", []))
                text = text.strip()
                if not text:
                    continue
                # Normalize soft hyphens for comparison
                text_norm = text.replace(SOFT_HYPHEN, "").strip()
                if not text_norm or len(text_norm) < 5:
                    continue
                y0 = line["bbox"][1]
                x0 = line["bbox"][0]
                if text_norm not in line_positions:
                    line_positions[text_norm] = []
                line_positions[text_norm].append((y0, x0))

    # Find lines that appear on multiple pages at similar y-positions
    header_footer_lines: set[str] = set()

    for text, positions in line_positions.items():
        if len(positions) >= min_occurrences:
            # Check if the y-positions cluster (within tolerance)
            y_vals = sorted(p[0] for p in positions)
            # If most occurrences are within a narrow y band, it's a header/footer
            distinct_y_clusters = _count_y_clusters(y_vals, tolerance=20.0)
            if distinct_y_clusters <= 3:  # Same position on up to 3 vertical bands
                header_footer_lines.add(text)

    if header_footer_lines:
        logger.debug(f"Detected {len(header_footer_lines)} header/footer line patterns")

    return header_footer_lines


def _count_y_clusters(y_vals: list[float], tolerance: float = 20.0) -> int:
    """Count how many distinct vertical clusters exist in a sorted list of y values."""
    if not y_vals:
        return 0
    clusters = 1
    current_cluster_start = y_vals[0]
    for y in y_vals[1:]:
        if y - current_cluster_start > tolerance:
            clusters += 1
            current_cluster_start = y
    return clusters


def _strip_headers_footers(text: str, header_footer_lines: set[str]) -> str:
    """Remove detected header/footer lines from page text."""
    if not header_footer_lines:
        return text

    lines = text.split("\n")
    result_lines: list[str] = []

    for line in lines:
        # Normalize for comparison
        line_norm = line.replace(SOFT_HYPHEN, "").strip()
        # Check if this line matches a header/footer pattern
        # Also check for partial matches (headers often have page numbers appended)
        is_header_footer = False
        for hf in header_footer_lines:
            if line_norm == hf:
                is_header_footer = True
                break
            # Check if header pattern is a prefix (e.g., "Chapter One" + "   42")
            if line_norm.startswith(hf):
                remainder = line_norm[len(hf):].strip()
                # If the remainder is just a number or empty, it's a header with page number
                if remainder.isdigit() or remainder == "":
                    is_header_footer = True
                    break

        if not is_header_footer:
            result_lines.append(line)

    return "\n".join(result_lines)


def _clean_text(text: str) -> str:
    """Apply text cleaning transformations.

    1. Remove soft hyphens (these mark word-break points in PDFs)
    2. Rejoin hard-hyphen line breaks ("con-\\nsequence" → "consequence")
    3. Strip standalone page numbers
    4. Strip running header/footer patterns (X + page_number)
    5. Assemble short lines into paragraphs
    6. Normalize whitespace
    7. Collapse excessive blank lines
    """
    # Step 1: Remove soft hyphens — they mark mid-word break points
    # in the PDF. Removing them rejoins the word fragments.
    text = text.replace(SOFT_HYPHEN, "")

    # Step 2: Rejoin hard hyphens at line breaks
    # "con-\\nsequence" → "consequence"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Step 3: Strip standalone page numbers (digits alone on a line)
    text = re.sub(r"^\s*\d{1,4}\s*$", "", text, flags=re.MULTILINE)

    # Step 4: Strip running headers with page numbers
    # Pattern: "Some Section Title   42" or "42  Some Section Title"
    text = re.sub(r"^[^\n]{5,80}\s{2,}\d{1,4}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d{1,4}\s{2,}[^\n]{5,80}\s*$", "", text, flags=re.MULTILINE)

    # Step 5: Assemble short lines into paragraphs
    # Lines that don't end with sentence-ending punctuation and are followed
    # by a line starting with lowercase should be merged with a space.
    lines = text.split("\n")
    result_lines: list[str] = []
    buffer = ""

    for line in lines:
        stripped = line.strip()

        if not stripped:
            # Blank line → paragraph break
            if buffer:
                result_lines.append(buffer)
                buffer = ""
            result_lines.append("")
            continue

        if buffer:
            prev_stripped = buffer.rstrip()
            # Determine whether to join or start a new paragraph
            # Join if:
            #  - Previous line doesn't end with sentence-ending punctuation, OR
            #  - Previous line ends with e.g., "etc.", "i.e."
            # AND current line starts with lowercase (continuation)
            ends_sentence = prev_stripped.endswith((".", "!", "?"))
            ends_with_abbreviation = prev_stripped.endswith(
                ("e.g.", "i.e.", "etc.", "vs.", "cf.", "p.", "pp.")
            )
            starts_lowercase = stripped[0:1].islower() if stripped else False

            if (not ends_sentence or ends_with_abbreviation) and starts_lowercase:
                # Join with a space
                buffer = prev_stripped + " " + stripped
            else:
                # Start a new paragraph
                result_lines.append(buffer)
                buffer = stripped
        else:
            buffer = stripped

    if buffer:
        result_lines.append(buffer)

    text = "\n".join(result_lines)

    # Step 6: Collapse excessive blank lines to max 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Step 7: Strip leading/trailing whitespace
    text = text.strip()

    return text


def extract_dingbat_manifest(pdf_path: str) -> dict[str, list[str]]:
    """Scan a PDF for dingbat/symbol font characters and build a replacement manifest.

    Uses PyMuPDF to inspect the font of every text span. When a span uses
    a font listed in DINGBATS_FONT_MAP, its characters are recorded as
    needing replacement.

    Returns:
        Dict mapping each dingbat character to a list of its replacement characters.
        E.g., {"Y": ["\u2022"]}

        The dict keys are the raw characters that need replacement in the
        Marker output. The values are the possible replacements (usually
        just one). The repair pipeline uses this manifest to apply
        targeted replacements instead of heuristic pattern matching.
    """
    doc = fitz.open(pdf_path)
    # Collect all dingbat character → replacement mappings found in the PDF
    char_replacements: dict[str, set[str]] = {}

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict")["blocks"]

        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    font = span.get("font", "")
                    text = span.get("text", "")
                    if not font or not text:
                        continue
                    # Check against all known dingbat fonts
                    for font_prefix, mapping in DINGBATS_FONT_MAP.items():
                        if font.startswith(font_prefix):
                            for ch in text:
                                if ch in mapping:
                                    replacement = mapping[ch]
                                    if ch not in char_replacements:
                                        char_replacements[ch] = set()
                                    char_replacements[ch].add(replacement)

    doc.close()

    # Convert sets to sorted lists (deterministic output)
    result: dict[str, list[str]] = {
        ch: sorted(repls) for ch, repls in sorted(char_replacements.items())
    }

    if result:
        logger.info(f"Dingbat manifest: {sum(len(v) for v in result.values())} character mapping(s) from {pdf_path}")
    else:
        logger.debug(f"No dingbat font characters found in {pdf_path}")

    return result