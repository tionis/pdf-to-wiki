"""Reference rewriting — convert page references to Obsidian wiki-links.

Takes the section tree + extracted text with {{page-ref:N}} annotations
and resolves them to [[section-slug|Section Title]] wiki-links by looking
up which section covers that printed page number.

This is a deterministic step — no LLM needed. It uses the section tree's
page range mappings to find the right section for each page reference.
"""

from __future__ import annotations

import re
from rulebook_wiki.models import SectionTree
from rulebook_wiki.logging import get_logger

logger = get_logger(__name__)


def rewrite_page_references(
    text: str,
    tree: SectionTree,
) -> str:
    """Rewrite {{page-ref:N}} annotations to Obsidian wiki-links.

    For each {{page-ref:N}}, find the section whose page range covers
    printed page N, and replace with [[section-slug|Section Title]].

    If multiple sections match (e.g., chapter-level sections), prefer
    leaf sections (no children) for more specific links.

    If no section matches, leave the annotation as-is.
    """
    # Build a lookup: printed page number → list of (section_id, title, is_leaf)
    page_to_sections: dict[int, list[tuple[str, str, bool]]] = {}

    for section_id, node in tree.nodes.items():
        # Use printed page labels if available, else pdf page index
        if node.printed_page_start is not None:
            start = _parse_page_label(node.printed_page_start)
            end = _parse_page_label(node.printed_page_end or node.printed_page_start)
        else:
            start = node.pdf_page_start
            end = node.pdf_page_end

        if start is None or end is None:
            continue

        is_leaf = len(node.children) == 0

        for page in range(start, end + 1):
            if page not in page_to_sections:
                page_to_sections[page] = []
            page_to_sections[page].append((section_id, node.title, is_leaf))

    # Also build a pdf-page-index lookup (using 0-based pdf_page_start/End)
    pdf_page_to_sections: dict[int, list[tuple[str, str, bool]]] = {}
    for section_id, node in tree.nodes.items():
        is_leaf = len(node.children) == 0
        for page in range(node.pdf_page_start, node.pdf_page_end + 1):
            if page not in pdf_page_to_sections:
                pdf_page_to_sections[page] = []
            pdf_page_to_sections[page].append((section_id, node.title, is_leaf))

    def _replace_ref(m):
        page_str = m.group(1)
        page_num = _parse_page_label(page_str)
        if page_num is None:
            return m.group(0)  # Keep original if can't parse

        # Try printed page labels first
        sections = page_to_sections.get(page_num, [])

        # If not found, try as PDF page index (0-based)
        if not sections:
            try:
                pdf_idx = int(page_str)
                sections = pdf_page_to_sections.get(pdf_idx, [])
            except ValueError:
                pass

        if not sections:
            # No matching section — keep the annotation
            return m.group(0)

        # Prefer leaf sections for more specific links
        leaf_sections = [s for s in sections if s[2]]  # is_leaf=True
        if leaf_sections:
            chosen = leaf_sections[0]
        else:
            chosen = sections[0]

        section_id, title, _ = chosen
        # Generate the Obsidian link slug (without source_id prefix)
        # The slug path is the part after source_id/
        parts = section_id.split("/", 1)
        if len(parts) > 1:
            slug = parts[1]
        else:
            slug = section_id

        return f"[[{slug}|{title}]]"

    return re.sub(r"\{\{page-ref:(\d+(?:-\d+)?)\}\}", _replace_ref, text)


def _parse_page_label(label: str) -> int | None:
    """Parse a page label string to an integer.

    Handles Arabic numerals only. Roman numerals return None
    (they're rare in page references within body text).
    """
    try:
        # Handle ranges like "43-45" — use the first number
        first = label.split("-")[0].strip()
        return int(first)
    except (ValueError, AttributeError):
        return None