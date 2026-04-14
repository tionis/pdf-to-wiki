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

from pathlib import PurePosixPath

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


def relative_markdown_link(from_note: str, to_note: str, title: str) -> str:
    """Compute a standard Markdown relative link between two notes.

    Takes two paths relative to the wiki root (e.g.,
    'books/source_id/chapter/section.md') and produces
    a standard Markdown link: [Title](../other/section.md)

    This is more portable than Obsidian wiki-links and works in
    any Markdown renderer.
    """
    from_p = PurePosixPath(from_note)
    to_p = PurePosixPath(to_note)
    rel = _compute_relative(from_p, to_p)
    return f"[{title}]({rel})"


def _compute_relative(from_path: PurePosixPath, to_path: PurePosixPath) -> str:
    """Compute a relative path from from_path to to_path.

    Both paths are relative to the same root.
    """
    try:
        # Simplest case: target is under the same parent directory
        return str(to_path.relative_to(from_path.parent))
    except ValueError:
        pass

    # General case: walk up to common ancestor, then down
    from_parts = from_path.parent.parts
    to_parts = to_path.parts

    # Find common prefix length
    common = 0
    for a, b in zip(from_parts, to_parts):
        if a == b:
            common += 1
        else:
            break

    # Go up from from_path's parent, then down to to_path
    up_count = len(from_parts) - common
    down_parts = to_parts[common:]

    up = [".."] * up_count
    result_parts = up + list(down_parts)
    return "/".join(result_parts)