"""PDF table detection and Markdown conversion.

Uses PyMuPDF's find_tables() to detect tables on PDF pages and converts
them to GitHub-flavored Markdown table syntax. This replaces the broken
plain-text table rendering that results from column-aware text extraction.

Table detection is done at the page level during extraction. Detected
tables are converted to Markdown and inserted at the correct position
in the page text, replacing the garbled plain-text regions.

Filtering:
  - Tables with fewer than 3 columns or 2 rows are considered false
    positives (often two-column list items misdetected as tables) and
    are skipped.
  - Adjacent empty columns are merged (PyMuPDF sometimes splits a wide
    column header across two detected columns).
"""

from __future__ import annotations

import re

import fitz  # PyMuPDF

from pdf_to_wiki.logging import get_logger

logger = get_logger(__name__)

# Minimum table dimensions to be considered a real table
MIN_TABLE_COLS = 3
MIN_TABLE_ROWS = 2


def extract_tables_as_markdown(page: fitz.Page) -> list[tuple[fitz.Rect, str]]:
    """Detect tables on a page and convert them to Markdown.

    Returns a list of (bbox, markdown_text) tuples, sorted by vertical
    position (top to bottom). The bbox can be used to identify which
    text blocks in the page should be replaced.

    Only tables with MIN_TABLE_COLS+ columns and MIN_TABLE_ROWS+ rows
    are included; smaller detections are typically false positives from
    two-column layouts.
    """
    results: list[tuple[fitz.Rect, str]] = []

    try:
        tables = page.find_tables()
    except Exception:
        return results

    for tab in tables.tables:
        if tab.col_count < MIN_TABLE_COLS or tab.row_count < MIN_TABLE_ROWS:
            continue

        rows = tab.extract()
        if not rows:
            continue

        # Merge adjacent columns where one is empty (column-split artifacts)
        merged_rows = _merge_empty_columns(rows)

        # Convert to Markdown table
        md = _rows_to_markdown_table(merged_rows)
        if md:
            results.append((fitz.Rect(tab.bbox), md))

    # Sort by vertical position
    results.sort(key=lambda r: r[1] and r[0].y0)
    return results


def _merge_empty_columns(rows: list[list[str]]) -> list[list[str]]:
    """Merge adjacent columns where one is effectively empty.

    PyMuPDF sometimes splits a wide column header across two detected
    columns, e.g., ['Availab', 'le'] or ['Cores', '']. When a column's
    data is empty in all rows (or very short fragments), merge it with
    the left neighbor.
    """
    if not rows or not rows[0]:
        return rows

    n_cols = len(rows[0])
    if n_cols <= 2:
        return rows

    # Find columns that are empty/fragment in all rows
    empty_cols: set[int] = set()
    for col_idx in range(n_cols):
        all_empty = True
        for row in rows:
            if col_idx < len(row):
                cell = row[col_idx].replace("\n", " ").strip()
                if cell and len(cell) > 2:
                    all_empty = False
                    break
        if all_empty:
            empty_cols.add(col_idx)

    if not empty_cols:
        return rows

    # Merge empty columns with their left neighbor
    merged_rows: list[list[str]] = []
    for row in rows:
        new_row: list[str] = []
        skip_next = False
        for col_idx, cell in enumerate(row):
            if skip_next:
                skip_next = False
                continue
            if col_idx in empty_cols and col_idx > 0 and new_row:
                # Merge this empty cell with the previous one
                prev = new_row[-1].replace("\n", " ").strip()
                frag = cell.replace("\n", " ").strip()
                if frag:
                    new_row[-1] = prev + frag
                skip_next = True  # Skip the next column if it's the pair
            else:
                new_row.append(cell.replace("\n", " ").strip())
        merged_rows.append(new_row)

    return merged_rows


def _rows_to_markdown_table(rows: list[list[str]]) -> str:
    """Convert extracted table rows to a GitHub-flavored Markdown table.

    All rows must have the same number of columns (padded if needed).
    The first row is treated as the header.
    """
    if not rows:
        return ""

    # Normalize: strip whitespace from cells, pad to equal column count
    max_cols = max(len(r) for r in rows)
    normalized: list[list[str]] = []
    for row in rows:
        padded = [c.replace("\n", " ").strip() for c in row]
        # Pad short rows
        while len(padded) < max_cols:
            padded.append("")
        normalized.append(padded)

    n_cols = len(normalized[0])
    if n_cols == 0:
        return ""

    # Build Markdown table
    lines: list[str] = []

    # Header row
    lines.append("| " + " | ".join(normalized[0]) + " |")

    # Separator row
    lines.append("| " + " | ".join("---" for _ in range(n_cols)) + " |")

    # Data rows
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def replace_tables_in_text(
    page_text: str,
    table_regions: list[tuple[fitz.Rect, str]],
    text_blocks: list[dict],
) -> str:
    """Replace table regions in the page text with Markdown tables.

    For each detected table, find the text blocks whose bounding boxes
    fall within the table region and replace them with the Markdown
    table text. Text blocks outside any table region are kept as-is.

    Args:
        page_text: The full page text (from column-aware extraction).
        table_regions: List of (bbox, markdown_text) from extract_tables_as_markdown.
        text_blocks: The text blocks used to construct page_text, with
            x0, y0, x1, y1, text fields.

    Returns:
        The page text with table regions replaced by Markdown tables.
    """
    if not table_regions:
        return page_text

    # Identify which blocks are inside table regions
    block_in_table: list[bool] = []
    for block in text_blocks:
        bx0, by0, bx1, by1 = block["x0"], block["y0"], block["x1"], block["y1"]
        inside = False
        for tab_bbox, _ in table_regions:
            # Check if the block center is inside the table bbox
            bcx = (bx0 + bx1) / 2
            bcy = (by0 + by1) / 2
            if (tab_bbox.x0 <= bcx <= tab_bbox.x1 and
                tab_bbox.y0 <= bcy <= tab_bbox.y1):
                inside = True
                break
        block_in_table.append(inside)

    # Group consecutive blocks that belong to the same table region
    # and figure out which table they belong to
    result_parts: list[str] = []
    i = 0
    blocks = text_blocks

    while i < len(blocks):
        if block_in_table[i]:
            # Find all consecutive blocks in this table region
            table_start = i
            while i < len(blocks) and block_in_table[i]:
                i += 1

            # Find which table region this group belongs to
            # Use the center of the first block in the group
            first_block = blocks[table_start]
            bcx = (first_block["x0"] + first_block["x1"]) / 2
            bcy = (first_block["y0"] + first_block["y1"]) / 2

            best_table = None
            for tab_bbox, md in table_regions:
                if (tab_bbox.x0 <= bcx <= tab_bbox.x1 and
                    tab_bbox.y0 <= bcy <= tab_bbox.y1):
                    best_table = md
                    break

            if best_table:
                result_parts.append(best_table)
            else:
                # Fallback: keep original text
                for j in range(table_start, i):
                    result_parts.append(blocks[j]["text"])
        else:
            result_parts.append(blocks[i]["text"])
            i += 1

    # Join with double newlines (same as the original extraction)
    return "\n\n".join(result_parts)