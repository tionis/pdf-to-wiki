"""Build the canonical section tree from TOC entries and page labels.

The section tree is the backbone of the entire pipeline. It defines
section boundaries, parent-child relationships, and page ranges.

Section IDs are namespaced: source_id/slug-path
Page ranges are computed by looking at adjacent TOC entries.
Printed page labels are mapped from the page-label data.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from pdf_to_wiki.cache.artifact_store import ArtifactStore
from pdf_to_wiki.cache.db import CacheDB
from pdf_to_wiki.cache.manifests import StepManifestStore
from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.logging import get_logger
from pdf_to_wiki.models import PageLabel, ProvenanceRecord, SectionNode, SectionTree, TocEntry

logger = get_logger(__name__)


def build_section_tree(
    source_id: str,
    config: WikiConfig,
    force: bool = False,
) -> SectionTree:
    """Build the canonical section tree for a registered PDF.

    Reads cached TOC and page-label artifacts, constructs the
    SectionTree, and persists it as a JSON artifact.

    This is a deterministic operation; no LLM is involved.
    """
    db = CacheDB(config.resolved_cache_db_path())
    artifacts = ArtifactStore(config.resolved_artifact_dir())
    manifests = StepManifestStore(db)

    source = db.get_pdf_source(source_id)
    if source is None:
        raise ValueError(f"No registered PDF with source_id={source_id!r}. Run 'register' first.")

    # Check cache
    if not force and manifests.is_completed(source_id, "section_tree"):
        cached = artifacts.load_json(source_id, "section_tree")
        if cached is not None:
            logger.info(f"Section tree for {source_id} already cached. Use --force to rebuild.")
            tree = SectionTree(**cached)
            db.close()
            return tree

    manifests.mark_running(source_id, "section_tree")

    # Load artifacts
    toc_data = artifacts.load_json(source_id, "toc")
    if toc_data is None:
        raise ValueError(f"No TOC data for {source_id}. Run 'toc' step first.")
    toc_entries = [TocEntry(**e) for e in toc_data]

    label_data = artifacts.load_json(source_id, "page_labels")
    page_labels: list[PageLabel] = []
    if label_data is not None:
        page_labels = [PageLabel(**e) for e in label_data]
    label_map: dict[int, str] = {pl.page_index: pl.label for pl in page_labels}

    # Build tree
    tree = _construct_tree(source_id, toc_entries, source.page_count, label_map)

    # Persist
    tree_data = tree.model_dump()
    artifacts.save_json(source_id, "section_tree", tree_data)

    now = datetime.now(timezone.utc).isoformat()
    prov = ProvenanceRecord(
        artifact_id=f"{source_id}/section_tree",
        source_id=source_id,
        step="section_tree",
        tool="pdf_to_wiki",
        tool_version="0.1.0",
        config_hash="",
        created_at=now,
    )
    db.insert_provenance(prov)
    manifests.mark_completed(source_id, "section_tree", artifact_path=f"{source_id}/section_tree.json")

    logger.info(f"Built section tree for {source_id}: {len(tree.nodes)} nodes, {len(tree.root_ids)} roots")
    db.close()
    return tree


def _construct_tree(
    source_id: str,
    toc: list[TocEntry],
    page_count: int,
    label_map: dict[int, str],
) -> SectionTree:
    """Construct a SectionTree from TOC entries and page labels.

    Algorithm:
    1. Walk the flat TOC in document order.
    2. Track a "last seen" stack where stack[level-1] is the most recent
       entry at that level.
    3. When a new entry appears at level L, its parent is
       stack[L-2] (the last entry at level L-1).
    4. Truncate the stack to depth L-1 before pushing, so deeper entries
       don't persist under a new sibling.
    5. Page ranges: each section spans from its pdf_page to one
       before the next entry at the same or higher level (or
       the end of the document).
    6. Section IDs: source_id / slug-path where slug-path
       chains ancestor and child slugs.
    """
    nodes: dict[str, SectionNode] = {}
    root_ids: list[str] = []

    # stack[level-1] = (section_id, slug_path) of the last entry at that level
    stack: list[tuple[str, str]] = []
    # Track TOC entries with section_ids for page-range computation
    ordered_sections: list[tuple[str, int, int]] = []  # (section_id, level, pdf_page)

    for entry in toc:
        level = entry.level
        title = entry.title
        slug = _slugify(title)

        # Trim stack: keep only ancestors at levels 1..level-1
        # stack[i] = last entry at level i+1
        # We need stack entries for levels 1 to level-1
        stack = stack[: level - 1]

        # Determine parent
        parent_id: str | None = None
        parent_slug_path: str = ""

        if level >= 2 and len(stack) >= level - 1:
            parent_id = stack[level - 2][0]
            parent_slug_path = stack[level - 2][1]

        # Build slug path
        if parent_slug_path:
            slug_path = f"{parent_slug_path}/{slug}"
        else:
            slug_path = slug

        section_id = f"{source_id}/{slug_path}"

        # Determine page range later; use placeholder for now
        node = SectionNode(
            section_id=section_id,
            source_id=source_id,
            title=title,
            slug=slug,
            level=level,
            parent_id=parent_id,
            children=[],
            pdf_page_start=entry.pdf_page,
            pdf_page_end=entry.pdf_page,  # Will be updated
            printed_page_start=label_map.get(entry.pdf_page),
            printed_page_end=label_map.get(entry.pdf_page),  # Will be updated
        )

        nodes[section_id] = node

        # Track parent-child
        if parent_id is not None and parent_id in nodes:
            nodes[parent_id].children.append(section_id)

        if level == 1:
            root_ids.append(section_id)

        # Push to stack at position level-1
        stack.append((section_id, slug_path))

        ordered_sections.append((section_id, level, entry.pdf_page))

    # Compute page ranges
    _compute_page_ranges(nodes, ordered_sections, page_count, label_map)

    return SectionTree(source_id=source_id, nodes=nodes, root_ids=root_ids)


def _compute_page_ranges(
    nodes: dict[str, SectionNode],
    ordered: list[tuple[str, int, int]],
    page_count: int,
    label_map: dict[int, str],
) -> None:
    """Fill in pdf_page_end and printed_page_end for each node.

    A section's end page is just before the start page of the next
    section at the same or higher (shallower) level —OR— the end
    of the document.
    """
    for i, (sid, level, start_page) in enumerate(ordered):
        end_page = start_page  # default: single-page section

        # Look ahead for the next entry at level <= current
        for j in range(i + 1, len(ordered)):
            _, next_level, next_page = ordered[j]
            if next_level <= level:
                end_page = max(start_page, next_page - 1)
                break
        else:
            # No subsequent entry at same or higher level; goes to end of doc
            end_page = page_count - 1

        nodes[sid].pdf_page_end = end_page
        nodes[sid].printed_page_start = label_map.get(start_page)
        nodes[sid].printed_page_end = label_map.get(end_page)


def _slugify(text: str) -> str:
    """Convert a section title to a URL/filename-friendly slug.

    - Unicode → ASCII (transliterate)
    - Strip parentheses and brackets
    - Lowercase
    - Non-alphanumeric → hyphens
    - Collapse multiple hyphens
    - Strip leading/trailing hyphens
    """
    # Transliterate unicode → ASCII where possible
    slug = unicodedata.normalize("NFKD", text)
    slug = slug.encode("ascii", "replace").decode("ascii")
    # Remove parentheses and brackets before slugifying
    slug = re.sub(r"[()\[\]{}]", "", slug)
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug or "untitled"