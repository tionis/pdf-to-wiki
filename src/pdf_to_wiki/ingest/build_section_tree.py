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

import click

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
        cached = artifacts.load_json(source.sha256, "section_tree")
        if cached is not None:
            logger.info(f"Section tree for {source_id} already cached. Use --force to rebuild.")
            tree = SectionTree(**cached)
            db.close()
            return tree

    # Dry-run: report what would be done without building
    if config.dry_run:
        click.echo(f"[DRY RUN] Would build section tree for {source_id}")
        click.echo(f"[DRY RUN]   Source: {source.path} ({source.page_count} pages)")
        db.close()
        return SectionTree(source_id=source_id)

    manifests.mark_running(source_id, "section_tree")

    # Load artifacts
    toc_data = artifacts.load_json(source.sha256, "toc")
    if toc_data is None:
        raise ValueError(f"No TOC data for {source_id}. Run 'toc' step first.")
    toc_entries = [TocEntry(**e) for e in toc_data]

    label_data = artifacts.load_json(source.sha256, "page_labels")
    page_labels: list[PageLabel] = []
    if label_data is not None:
        page_labels = [PageLabel(**e) for e in label_data]
    label_map: dict[int, str] = {pl.page_index: pl.label for pl in page_labels}

    # Build tree
    tree = _construct_tree(source_id, toc_entries, source.page_count, label_map)

    # Persist
    tree_data = tree.model_dump()
    artifacts.save_json(source.sha256, "section_tree", tree_data)

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

    # Detect and unwrap single-root pattern where the root's slug
    # matches the source_id (common when PDF title matches filename)
    tree = SectionTree(source_id=source_id, nodes=nodes, root_ids=root_ids)
    tree = _unwrap_single_root(tree)

    return tree


def _unwrap_single_root(tree: SectionTree) -> SectionTree:
    """Detect and unwrap a single-root pattern where the root slug matches source_id.

    When a PDF has a single L1 TOC entry whose title slugifies to the same
    string as the source_id (derived from the filename), the result is
    redundant nesting like:

        books/chronicles-of-darkness/chronicles-of-darkness/chronicles-of-darkness/...

    This pattern is common when the PDF's top-level bookmark is the
    book title. Instead of nesting the book's content under a wrapper
    whose name duplicates the source_id, we promote the wrapper's
    children to be direct children of the source_id directory.

    After unwrapping:
        books/chronicles-of-darkness/introduction/...
        books/chronicles-of-darkness/apt-3b.md
        ...

    The wrapper node itself becomes the book-level index.

    Only unwraps when there is exactly one root AND its slug matches
    the source_id (with some fuzzy matching for hyphen/space differences).
    """
    if len(tree.root_ids) != 1:
        return tree

    root_id = tree.root_ids[0]
    root = tree.nodes[root_id]

    # Check if root slug matches source_id (fuzzy: allow minor differences)
    root_slug = root.slug.lower().replace("-", " ")
    source_slug = tree.source_id.lower().replace("-", " ")

    if root_slug != source_slug:
        return tree  # Not a matching single-root pattern

    logger.info(
        f"Unwrapping single root '{root.title}' (slug='{root.slug}' matches "
        f"source_id='{tree.source_id}'). Promoting {len(root.children)} children."
    )

    # Promote the wrapper's children to be direct children of the source_id
    # by removing the wrapper node from the ID chain.
    #
    # Before: source_id/wrapper_slug/child_slug  →  source_id/child_slug
    # After:  source_id/child_slug
    #
    # Additionally, if any promoted child has the same slug as source_id,
    # deduplicate its slug to avoid redundant nesting like:
    #   books/chronicles-of-darkness/chronicles-of-darkness/...
    # The conflicting slug gets a disambiguating suffix.
    new_nodes: dict[str, SectionNode] = {}
    new_root_ids: list[str] = []

    def _remap_node(node: SectionNode, new_parent_id: str | None, depth_offset: int, new_slug: str | None = None) -> SectionNode:
        """Rebuild a node with new section_id and parent_id."""
        old_id = node.section_id
        wrapper_prefix = f"{tree.source_id}/{root.slug}/"
        slug = new_slug if new_slug is not None else node.slug

        if old_id.startswith(wrapper_prefix):
            rest = old_id[len(wrapper_prefix):]
            # If we're replacing the first slug component (new_slug given),
            # replace it in the rest of the path
            if new_slug is not None and rest.startswith(node.slug + "/"):
                rest = new_slug + rest[len(node.slug):]
            elif new_slug is not None and rest == node.slug:
                rest = new_slug
            new_id = tree.source_id + "/" + rest
        elif old_id == root_id:
            return None
        else:
            new_id = old_id

        new_node = SectionNode(
            section_id=new_id,
            source_id=node.source_id,
            title=node.title,
            slug=slug,
            level=node.level + depth_offset,
            parent_id=new_parent_id,
            children=[],
            pdf_page_start=node.pdf_page_start,
            pdf_page_end=node.pdf_page_end,
            printed_page_start=node.printed_page_start,
            printed_page_end=node.printed_page_end,
        )
        return new_node

    # Process the wrapper's children — they become roots
    slug_dedup: dict[str, str] = {}  # old_slug -> new_slug for collisions
    for child_id in root.children:
        child = tree.nodes[child_id]
        # Deduplicate: if child's slug matches source_id, rename it
        new_slug = child.slug
        if child.slug.lower().replace("-", " ") == source_slug:
            # Try disambiguating by appending a suffix from the title
            # e.g., "Chronicles of Darkness" -> "chronicles-of-darkness-core-rules"
            new_slug = _dedup_slug(child.slug, child.title, tree.source_id)
            slug_dedup[child.slug] = new_slug
            logger.info(
                f"Deduplicating slug: '{child.slug}' -> '{new_slug}' "
                f"(collides with source_id '{tree.source_id}')"
            )

        new_child = _remap_node(child, None, -1, new_slug=new_slug if new_slug != child.slug else None)
        if new_child is None:
            continue
        new_nodes[new_child.section_id] = new_child
        new_root_ids.append(new_child.section_id)

        # Recursively remap the child's entire subtree
        _remap_subtree(child_id, tree, new_nodes, -1, slug_dedup=slug_dedup)

    return SectionTree(
        source_id=tree.source_id,
        nodes=new_nodes,
        root_ids=new_root_ids,
    )


def _remap_subtree(
    parent_old_id: str,
    tree: SectionTree,
    new_nodes: dict[str, SectionNode],
    depth_offset: int,
    slug_dedup: dict[str, str] | None = None,
) -> None:
    """Recursively remap all descendants of a node."""
    parent = tree.nodes[parent_old_id]
    parent_new_id = _compute_new_id(parent_old_id, tree, slug_dedup=slug_dedup)

    new_children = []
    for child_id in parent.children:
        child = tree.nodes[child_id]
        new_child_id = _compute_new_id(child_id, tree, slug_dedup=slug_dedup)

        new_node = SectionNode(
            section_id=new_child_id,
            source_id=child.source_id,
            title=child.title,
            slug=child.slug,
            level=child.level + depth_offset,
            parent_id=parent_new_id,
            children=[],
            pdf_page_start=child.pdf_page_start,
            pdf_page_end=child.pdf_page_end,
            printed_page_start=child.printed_page_start,
            printed_page_end=child.printed_page_end,
        )
        new_nodes[new_child_id] = new_node
        new_children.append(new_child_id)

        # Recurse into grandchildren
        if child.children:
            _remap_subtree(child_id, tree, new_nodes, depth_offset, slug_dedup=slug_dedup)

    # Update parent's children list
    if parent_new_id in new_nodes:
        new_nodes[parent_new_id] = new_nodes[parent_new_id].model_copy(
            update={"children": new_children}
        )


def _compute_new_id(old_id: str, tree: SectionTree, slug_dedup: dict[str, str] | None = None) -> str:
    """Compute a new section_id by removing the wrapper prefix."""
    root = tree.nodes[tree.root_ids[0]]
    wrapper_prefix = f"{tree.source_id}/{root.slug}/"
    if old_id.startswith(wrapper_prefix):
        rest = old_id[len(wrapper_prefix):]
        # Apply slug deduplication if provided
        if slug_dedup:
            for old_slug, new_slug in slug_dedup.items():
                if rest.startswith(old_slug + "/"):
                    rest = new_slug + rest[len(old_slug):]
                    break
                elif rest == old_slug:
                    rest = new_slug
                    break
        return tree.source_id + "/" + rest
    return old_id


def _dedup_slug(original_slug: str, title: str, source_id: str) -> str:
    """Create a disambiguated slug when it collides with the source_id.

    Tries suffixes derived from the title until we get a unique slug.
    E.g., 'chronicles-of-darkness' (title: 'Chronicles of Darkness')
    -> 'chronicles-of-darkness-rules'
    """
    # Try adding meaningful words from the title
    title_words = title.lower().replace("-", " ").split()
    # Skip the words that are already in the slug
    slug_words = set(original_slug.lower().split("-"))
    suffix_candidates = [w for w in title_words if w not in slug_words and len(w) > 2]
    # Also try generic disambiguators
    suffix_candidates.extend(["rules", "content", "main"])

    for suffix in suffix_candidates:
        candidate = f"{original_slug}-{suffix}"
        if candidate != source_id:
            return candidate

    # Fallback: just append a number
    return f"{original_slug}-1"


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