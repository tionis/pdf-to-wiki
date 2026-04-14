"""Deterministic Obsidian-friendly path generation from section trees.

Path rules:
- Top-level sections (level 1) become directories with an index.md
- Leaf sections (no children) become individual .md files in their parent directory
- Sections with children become directories with an index.md
- Paths are deterministic given the section tree
- Numeric prefix for ordering: not used by default; slug-only for cleaner URLs
- Source ID is used as namespace prefix for multi-book wikis
"""

from __future__ import annotations

from pathlib import Path

from rulebook_wiki.models import SectionNode, SectionTree


def section_path(node: SectionNode, tree: SectionTree) -> str:
    """Compute the relative directory path for a section node.

    A section with children becomes a directory.
    A section without children becomes a file prefix.

    The path includes the source_id as a namespace prefix to
    avoid collisions when multiple books share the same wiki.
    Root sections are nested under their source_id directory.
    """
    parts: list[str] = []
    current: SectionNode | None = node
    while current is not None:
        parts.append(current.slug)
        current = tree.nodes.get(current.parent_id) if current.parent_id else None
    parts.reverse()
    # Prepend source_id as namespace
    slug_path = "/".join(parts)
    return f"{tree.source_id}/{slug_path}"


def section_note_path(node: SectionNode, tree: SectionTree, books_dir: str = "books") -> str:
    """Compute the full relative output path for a section's Markdown note.

    Sections with children → <path>/index.md
    Sections without children → <path>.md
    """
    base = section_path(node, tree)
    if node.children:
        return f"{books_dir}/{base}/index.md"
    else:
        return f"{books_dir}/{base}.md"