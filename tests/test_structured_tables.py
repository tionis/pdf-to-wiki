"""Tests for structured table data extraction."""

from __future__ import annotations

from pdf_to_wiki.repair.structured_tables import (
    PipeTable,
    extract_pipe_tables,
    extract_structured_tables,
    parse_pipe_table,
)


class TestParsePipeTable:
    """Tests for the parse_pipe_table function."""

    def test_simple_table(self):
        """Parse a basic two-column pipe table."""
        md = (
            "| Name | Cost |\n"
            "|------|------|\n"
            "| Sword | 10gp |\n"
            "| Shield | 5gp |"
        )
        table = parse_pipe_table(md)
        assert table is not None
        assert table.headers == ["Name", "Cost"]
        assert len(table.rows) == 2
        assert table.rows[0]["Name"] == "Sword"
        assert table.rows[0]["Cost"] == "10gp"
        assert table.rows[1]["Name"] == "Shield"

    def test_three_columns(self):
        """Parse a three-column table."""
        md = (
            "| Weapon | Damage | Range |\n"
            "|--------|--------|-------|\n"
            "| Bow | 1d8 | 100ft |\n"
            "| Knife | 1d4 | 5ft |"
        )
        table = parse_pipe_table(md)
        assert table is not None
        assert table.headers == ["Weapon", "Damage", "Range"]
        assert table.rows[0]["Range"] == "100ft"

    def test_no_leading_trailing_pipes(self):
        """Parse tables without leading/trailing pipes."""
        md = (
            "Name | Cost\n"
            "-----|-----\n"
            "Sword | 10gp"
        )
        table = parse_pipe_table(md)
        assert table is not None
        assert table.headers == ["Name", "Cost"]
        assert len(table.rows) == 1

    def test_alignment_markers(self):
        """Alignment markers (:) in separator are ignored."""
        md = (
            "| Left | Center | Right |\n"
            "|:-----|:------:|------:|\n"
            "| a | b | c |"
        )
        table = parse_pipe_table(md)
        assert table is not None
        assert table.headers == ["Left", "Center", "Right"]

    def test_empty_cells(self):
        """Empty cells are preserved as empty strings."""
        md = (
            "| Name | Cost |\n"
            "|------|------|\n"
            "| Sword |  |\n"
            "|  | 5gp |"
        )
        table = parse_pipe_table(md)
        assert table is not None
        assert table.rows[0]["Cost"] == ""
        assert table.rows[1]["Name"] == ""

    def test_empty_headers_get_placeholder(self):
        """Empty headers get placeholder names (col_1, col_2...)."""
        md = (
            "|  | Cost |\n"
            "|--|------|\n"
            "| Sword | 10gp |"
        )
        table = parse_pipe_table(md)
        assert table is not None
        assert table.headers[0] == "col_1"
        assert table.headers[1] == "Cost"

    def test_duplicate_headers_deduplicated(self):
        """Duplicate headers get suffixes (_1, _2...)."""
        md = (
            "| Name | Name |\n"
            "|------|------|\n"
            "| a | b |"
        )
        table = parse_pipe_table(md)
        assert table is not None
        assert "Name" in table.headers
        assert "Name_1" in table.headers

    def test_too_short_returns_none(self):
        """Text with fewer than 3 lines returns None."""
        assert parse_pipe_table("| A | B |") is None
        assert parse_pipe_table("") is None

    def test_no_separator_returns_none(self):
        """Text without a separator line returns None."""
        md = "| A | B |\n| c | d |"
        assert parse_pipe_table(md) is None

    def test_pipe_table_to_dict(self):
        """PipeTable.to_dict() produces expected structure."""
        md = (
            "| Name | Cost |\n"
            "|------|------|\n"
            "| Sword | 10gp |"
        )
        table = parse_pipe_table(md)
        assert table is not None
        d = table.to_dict()
        assert "headers" in d
        assert "rows" in d
        assert d["headers"] == ["Name", "Cost"]
        assert len(d["rows"]) == 1

    def test_to_csv(self):
        """PipeTable.to_csv() produces valid CSV."""
        md = (
            "| Name | Cost |\n"
            "|------|------|\n"
            "| Sword | 10gp |\n"
            "| Shield | 5gp |"
        )
        table = parse_pipe_table(md)
        assert table is not None
        csv_text = table.to_csv()
        assert "Name,Cost" in csv_text
        assert "Sword,10gp" in csv_text

    def test_br_in_cells_normalized(self):
        """<br> remainders (/ separators) in cells are normalized."""
        md = (
            "| Property | Value |\n"
            "|----------|-------|\n"
            "| Tag | Fragile / Volatile |"
        )
        table = parse_pipe_table(md)
        assert table is not None
        assert "Fragile / Volatile" in table.rows[0]["Value"]


class TestExtractPipeTables:
    """Tests for extracting multiple pipe tables from text."""

    def test_single_table_in_text(self):
        """Extract a single table from surrounding Markdown."""
        text = (
            "# Equipment\n\n"
            "Here are the weapons:\n\n"
            "| Name | Damage |\n"
            "|------|--------|\n"
            "| Sword | 1d8 |\n"
            "| Bow | 1d6 |\n\n"
            "More text here."
        )
        tables = extract_pipe_tables(text, section_id="equip")
        assert len(tables) == 1
        assert tables[0].headers == ["Name", "Damage"]
        assert tables[0].section_id == "equip"

    def test_multiple_tables_in_text(self):
        """Extract multiple tables from the same text."""
        text = (
            "# Chapter\n\n"
            "| Weapon | Damage |\n"
            "|--------|--------|\n"
            "| Sword | 1d8 |\n\n"
            "Some text.\n\n"
            "| Armor | AC |\n"
            "|-------|----|\n"
            "| Chain | 16 |\n"
        )
        tables = extract_pipe_tables(text)
        assert len(tables) == 2
        assert tables[0].headers == ["Weapon", "Damage"]
        assert tables[1].headers == ["Armor", "AC"]

    def test_no_tables(self):
        """Text without pipe tables returns empty list."""
        text = "# Just a heading\n\nSome paragraph text."
        tables = extract_pipe_tables(text)
        assert tables == []

    def test_caption_detected(self):
        """Short text before a table is captured as caption."""
        text = (
            "Weapon statistics:\n\n"
            "| Weapon | Damage |\n"
            "|--------|--------|\n"
            "| Sword | 1d8 |\n"
        )
        tables = extract_pipe_tables(text)
        assert len(tables) == 1
        assert tables[0].caption == "Weapon statistics:"


class TestExtractStructuredTables:
    """Tests for the full structured extraction from section text data."""

    def test_extract_from_sections(self):
        """Extract tables from a dict of section texts."""
        text_data = {
            "weapons": (
                "| Weapon | Damage |\n"
                "|--------|--------|\n"
                "| Sword | 1d8 |\n"
                "| Bow | 1d6 |\n"
            ),
            "spells": "# Spells\n\nNo tables here.",
            "armor": (
                "| Armor | AC |\n"
                "|-------|----|\n"
                "| Leather | 11 |\n"
                "| Chain | 16 |\n"
            ),
        }
        result = extract_structured_tables(text_data, min_rows=1, min_cols=2)
        assert len(result) == 2
        section_ids = {t["section_id"] for t in result}
        assert "weapons" in section_ids
        assert "armor" in section_ids

    def test_min_rows_filter(self):
        """Tables below min_rows are excluded."""
        text_data = {
            "test": (
                "| A | B |\n"
                "|---|---|\n"  # No data rows
            ),
        }
        result = extract_structured_tables(text_data, min_rows=1, min_cols=2)
        assert len(result) == 0

    def test_min_cols_filter(self):
        """Tables below min_cols are excluded."""
        text_data = {
            "test": (
                "| A |\n"
                "|---|\n"
                "| x |\n"
            ),
        }
        result = extract_structured_tables(text_data, min_rows=1, min_cols=2)
        assert len(result) == 0

    def test_sections_without_pipes_skipped(self):
        """Sections with no pipe characters are skipped efficiently."""
        text_data = {
            "s1": "Just plain text.",
            "s2": "Also no tables.",
        }
        result = extract_structured_tables(text_data)
        assert len(result) == 0