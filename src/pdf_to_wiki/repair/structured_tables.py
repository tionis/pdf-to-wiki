"""Structured table data extraction from Markdown pipe tables.

Parses Markdown pipe-table text into structured JSON data (list of dicts)
suitable for downstream processing like VTT import, spreadsheet export,
or structured queries.

This module works on the pipe-table Markdown that Marker and Docling engines
produce. It does NOT extract tables from PDFs directly — it parses the
Markdown output from the extraction pipeline.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field

from pdf_to_wiki.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PipeTable:
    """A parsed Markdown pipe table with structured data.

    Attributes:
        headers: List of column header strings.
        rows: List of row dicts, each mapping header → cell value.
        raw_text: The original Markdown pipe-table text.
        caption: Optional table caption (from preceding paragraph).
        section_id: Source section ID where this table was found.
    """

    headers: list[str]
    rows: list[dict[str, str]]
    raw_text: str = ""
    caption: str = ""
    section_id: str = ""

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON output."""
        return {
            "headers": self.headers,
            "rows": self.rows,
            "caption": self.caption,
            "section_id": self.section_id,
        }

    def to_csv(self) -> str:
        """Export as CSV text."""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=self.headers)
        writer.writeheader()
        writer.writerows(self.rows)
        return output.getvalue()

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.headers)


# Regex identifying a pipe-table separator line:
# | --- | --- | or |:---:|---:| etc.
_SEPARATOR_RE = re.compile(
    r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$"
)


def parse_pipe_table(text: str) -> PipeTable | None:
    """Parse a single Markdown pipe table into structured data.

    Expects a complete pipe table (header row, separator, data rows).
    Returns None if the text doesn't contain a valid pipe table.

    Handles:
    - Standard pipe tables: | H1 | H2 |\\n| --- | --- |\\n| a | b |
    - Leading/trailing pipes (optional)
    - Alignment markers (:---:, ---:, :---)
    - Multi-line cell content (joined with " / ")
    - Empty cells
    """
    lines = text.strip().split("\n")
    if len(lines) < 3:
        return None  # Need at least header + separator + one data row

    # Find the separator line
    sep_idx = None
    for i, line in enumerate(lines):
        if _SEPARATOR_RE.match(line.strip()):
            sep_idx = i
            break

    if sep_idx is None or sep_idx == 0:
        return None  # No separator found, or separator is first line

    # Parse header row (line before separator)
    headers = _parse_pipe_row(lines[sep_idx - 1])
    if not headers:
        return None

    # Clean headers: strip whitespace, normalize empty headers
    cleaned_headers: list[str] = []
    for h in headers:
        h = h.strip()
        if not h:
            # Generate a placeholder for empty headers
            h = f"col_{len(cleaned_headers) + 1}"
        cleaned_headers.append(h)

    # Deduplicate headers by appending suffix
    seen: dict[str, int] = {}
    final_headers: list[str] = []
    for h in cleaned_headers:
        if h in seen:
            seen[h] += 1
            final_headers.append(f"{h}_{seen[h]}")
        else:
            seen[h] = 0
            final_headers.append(h)

    # Parse data rows (after separator)
    rows: list[dict[str, str]] = []
    for line in lines[sep_idx + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        # Stop at non-table lines
        if "|" not in stripped:
            break
        # Skip additional separator lines (rare but possible)
        if _SEPARATOR_RE.match(stripped):
            continue

        cells = _parse_pipe_row(line)
        if not cells:
            continue

        # Build row dict, handling mismatched column counts
        row: dict[str, str] = {}
        for j, header in enumerate(final_headers):
            if j < len(cells):
                # Clean cell: strip whitespace, normalize <br> remainders
                val = cells[j].strip()
                val = re.sub(r"\s+/\s+", " / ", val)  # Normalize <br> replacement
                row[header] = val
            else:
                row[header] = ""
        rows.append(row)

    if not rows:
        return None

    return PipeTable(
        headers=final_headers,
        rows=rows,
        raw_text=text.strip(),
    )


def _parse_pipe_row(line: str) -> list[str]:
    """Parse a single pipe-table row into cell values.

    Handles both '| a | b |' and 'a | b' formats.
    """
    stripped = line.strip()

    # Remove leading and trailing pipes
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]

    # Split on pipes, but handle escaped pipes
    # (rare in TTRPG content but good to handle)
    cells = stripped.split("|")
    return cells


def extract_pipe_tables(text: str, section_id: str = "") -> list[PipeTable]:
    """Extract all pipe tables from a Markdown text.

    Scans the text for pipe-table blocks and parses each one.
    Tables are identified by the separator line pattern.

    Args:
        text: Markdown text that may contain pipe tables.
        section_id: Source section ID to tag extracted tables.

    Returns:
        List of PipeTable objects found in the text.
    """
    lines = text.split("\n")
    tables: list[PipeTable] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if "|" in line and not _SEPARATOR_RE.match(line):
            # Check if this could be a table header
            # Look ahead for a separator line
            if i + 1 < len(lines) and _SEPARATOR_RE.match(lines[i + 1].strip()):
                # Found a table — collect all contiguous table lines
                table_lines = [lines[i], lines[i + 1]]
                j = i + 2
                while j < len(lines):
                    stripped = lines[j].strip()
                    if not stripped:
                        break
                    if "|" not in stripped:
                        break
                    if _SEPARATOR_RE.match(stripped):
                        # Another separator — skip
                        table_lines.append(lines[j])
                        j += 1
                        continue
                    table_lines.append(lines[j])
                    j += 1

                table_text = "\n".join(table_lines)
                table = parse_pipe_table(table_text)
                if table is not None:
                    # Try to find a caption in preceding lines
                    caption = ""
                    for k in range(i - 1, max(i - 4, -1), -1):
                        cap_line = lines[k].strip()
                        if cap_line and not cap_line.startswith("|") and not cap_line.startswith("#"):
                            # Check if it looks like a table caption
                            # (short paragraph directly before table, often bold or italic)
                            clean = re.sub(r"[*_`]", "", cap_line)
                            if len(clean) < 100:
                                caption = clean
                            break
                        elif cap_line.startswith("#"):
                            break

                    table.caption = caption
                    table.section_id = section_id
                    tables.append(table)

                i = j
                continue

        i += 1

    return tables


def extract_structured_tables(
    extract_text_data: dict[str, str],
    min_rows: int = 2,
    min_cols: int = 2,
) -> list[dict]:
    """Extract all pipe tables from extracted text data as structured JSON.

    This is the main entry point for structured table extraction from the
    pipeline's output. It scans all sections for pipe tables and returns
    them as a list of serializable dicts.

    Args:
        extract_text_data: Dict mapping section_id → extracted text (from extract_text.json).
        min_rows: Minimum number of data rows for a table to be included.
        min_cols: Minimum number of columns for a table to be included.

    Returns:
        List of table dicts suitable for JSON serialization.
    """
    all_tables: list[dict] = []
    total_sections_with_tables = 0

    for section_id, text in extract_text_data.items():
        if not text or "|" not in text:
            continue

        tables = extract_pipe_tables(text, section_id=section_id)
        section_tables = []

        for table in tables:
            # Filter by minimum dimensions
            if table.row_count < min_rows or table.column_count < min_cols:
                continue
            section_tables.append(table.to_dict())

        if section_tables:
            total_sections_with_tables += 1
            all_tables.extend(section_tables)

    logger.info(
        f"Extracted {len(all_tables)} structured tables from "
        f"{total_sections_with_tables} sections "
        f"(min {min_rows} rows × {min_cols} cols)"
    )

    return all_tables