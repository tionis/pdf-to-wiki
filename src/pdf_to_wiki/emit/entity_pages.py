"""Entity page generation from glossary entries.

Generates cross-reference stub pages for glossary terms under an
`entities/` namespace within the book directory. Each stub page
links back to the section(s) where the term is defined or used.

This creates a browsable index of game concepts, enabling navigation
from any entity stub to its full definition and all sections that
reference it.

Entity pages are generated from the glossary.json artifact produced
by the glossary extraction step. They include:
- Term name as the page heading
- Short definition excerpt from the glossary
- Links to sections where the term is defined (from glossary provenance)
- "See also" links to other entity pages mentioned in the definition

Stubs are placed at:
    books/<source_id>/entities/<slug>.md

An entities/index.md page provides an alphabetical index of all entities.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from pdf_to_wiki.logging import get_logger

if TYPE_CHECKING:
    from pdf_to_wiki.config import WikiConfig
    from pdf_to_wiki.models import SectionTree

logger = get_logger(__name__)


# ── Slug generation ────────────────────────────────────────────────────


def entity_slug(term: str) -> str:
    """Generate a filesystem-safe slug for an entity term.

    Lowercase, strip non-alphanumeric, hyphens for spaces.
    E.g., "10 Again" → "10-again", "Breaking Point" → "breaking-point"
    """
    slug = term.lower().strip()
    # Replace spaces with hyphens
    slug = re.sub(r'\s+', '-', slug)
    # Remove non-alphanumeric/hyphen characters
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    # Collapse multiple hyphens
    slug = re.sub(r'-+', '-', slug)
    # Strip leading/trailing hyphens
    slug = slug.strip('-')
    return slug or "unknown"


# ── Entity stub generation ────────────────────────────────────────────


def generate_entity_pages(
    source_id: str,
    config: "WikiConfig",
    force: bool = False,
) -> dict[str, str]:
    """Generate entity stub pages from glossary entries.

    Creates individual entity pages and an entities/index.md page
    within the book directory. Each entity page links back to its
    source definition section(s).

    Args:
        source_id: The registered PDF source ID.
        config: Pipeline configuration.
        force: Force regeneration even if entities already exist.

    Returns:
        Dict mapping term → relative output path.
    """
    from pdf_to_wiki.cache.artifact_store import ArtifactStore
    from pdf_to_wiki.cache.db import CacheDB
    from pdf_to_wiki.emit.obsidian_paths import relative_markdown_link

    artifacts = ArtifactStore(config.resolved_artifact_dir())
    output_dir = config.resolved_output_dir()
    books_dir = config.books_dir

    # Resolve SHA-256 for content-addressed artifact lookup
    db = CacheDB(config.resolved_cache_db_path())
    sha256 = db.get_sha256(source_id)
    db.close()
    content_key = sha256 or source_id  # fallback

    # Load glossary data
    glossary_data = artifacts.load_json(content_key, "glossary")
    if not glossary_data:
        logger.warning(f"No glossary data for {source_id}. Run 'glossary' command first.")
        return {}

    # Load section tree for link computation
    tree_data = artifacts.load_json(content_key, "section_tree")
    if tree_data is None:
        logger.warning(f"No section tree for {source_id}. Cannot create entity links.")
        return {}
    from pdf_to_wiki.models import SectionTree as ST
    tree = ST(**tree_data)

    entities_dir = output_dir / books_dir / source_id / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)

    # Build a set of all glossary terms for cross-referencing
    all_terms = {e["term"].lower(): e["term"] for e in glossary_data}

    emit_manifest: dict[str, str] = {}

    # Generate individual entity pages
    for entry in glossary_data:
        term = entry["term"]
        definition = entry["definition"]
        section_id = entry.get("section_id", "")
        page = entry.get("page")
        source_type = entry.get("source_type", "lexicon")

        slug = entity_slug(term)
        rel_path = f"{books_dir}/{source_id}/entities/{slug}.md"
        abs_path = output_dir / rel_path

        # Build entity page content
        lines: list[str] = []

        # YAML frontmatter
        fm = {
            "source_pdf_id": source_id,
            "entity_type": "glossary_term",
            "source_type": source_type,
            "page": page,
            "aliases": [term],
            "tags": ["rulebook", "imported", "entity", source_type],
        }
        if section_id:
            fm["defined_in"] = section_id

        import yaml
        lines.append("---")
        lines.append(yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).strip())
        lines.append("---")
        lines.append("")

        # Heading
        lines.append(f"# {term}")
        lines.append("")

        # Definition excerpt
        # Truncate very long definitions for readability
        if len(definition) > 500:
            defn_display = definition[:497] + "..."
        else:
            defn_display = definition
        lines.append(f"> {defn_display}")
        lines.append("")

        # Source link: link back to the section where this term is defined
        if section_id and section_id in tree.nodes:
            node = tree.nodes[section_id]
            target_path = node.markdown_output_path or ""
            if target_path:
                from_path = f"{books_dir}/{source_id}/entities/{slug}.md"
                link = relative_markdown_link(from_path, target_path, node.title)
                page_label = node.printed_page_start or str(node.pdf_page_start)
                lines.append(f"**Defined in:** {link} (p. {page_label})")
                lines.append("")

        # "See also" links: check if other glossary terms appear in the definition
        see_also = _find_related_terms(term, definition, all_terms)
        if see_also:
            see_also_links = []
            for related_term in sorted(see_also, key=str.lower):
                related_slug = entity_slug(related_term)
                from_path = f"{books_dir}/{source_id}/entities/{slug}.md"
                to_path = f"{books_dir}/{source_id}/entities/{related_slug}.md"
                link = relative_markdown_link(from_path, to_path, related_term)
                see_also_links.append(link)
            lines.append("**See also:** " + " · ".join(see_also_links))
            lines.append("")

        abs_path.write_text("\n".join(lines), encoding="utf-8")
        emit_manifest[term] = rel_path
        logger.debug(f"Emitted entity page: {rel_path}")

    # Generate entities/index.md
    _emit_entities_index(glossary_data, tree, entities_dir, output_dir, books_dir, source_id)

    logger.info(f"Generated {len(emit_manifest)} entity pages for {source_id}")
    return emit_manifest


def _find_related_terms(
    term: str,
    definition: str,
    all_terms: dict[str, str],
    max_links: int = 8,
) -> list[str]:
    """Find other glossary terms mentioned in this term's definition.

    Searches for case-insensitive matches of other glossary terms
    within the definition text. Skips the term itself and very short
    terms (≤2 chars) to avoid false positives.

    Args:
        term: The current term (excluded from results).
        definition: The definition text to search.
        all_terms: Dict of lowercase_term → canonical_term.
        max_links: Maximum number of "see also" links.

    Returns:
        List of canonical term names found in the definition.
    """
    related = []
    term_lower = term.lower()
    defn_lower = definition.lower()

    # Sort by length descending — prefer longer, more specific matches
    for other_lower, other_canonical in sorted(
        all_terms.items(), key=lambda x: len(x[0]), reverse=True
    ):
        if other_lower == term_lower:
            continue
        if len(other_lower) <= 2:
            continue  # Skip very short terms (e.g., "XP")

        # Check for word-boundary match to avoid partial matches
        # E.g., "dice" shouldn't match "dice pool" if "dice pool" is also a term
        if re.search(r'\b' + re.escape(other_lower) + r'\b', defn_lower):
            # Don't add if a longer term that contains this one is already added
            is_subsumed = False
            for already in related:
                if other_lower in already.lower() and other_lower != already.lower():
                    is_subsumed = True
                    break
            if not is_subsumed:
                related.append(other_canonical)

        if len(related) >= max_links:
            break

    return related


def _emit_entities_index(
    glossary_data: list[dict],
    tree: "SectionTree",
    entities_dir: Path,
    output_dir: Path,
    books_dir: str,
    source_id: str,
) -> None:
    """Emit an entities/index.md with an alphabetical listing of all entities.

    Provides letter-heading navigation and one-line entries linking to
    each entity stub page.
    """
    from pdf_to_wiki.emit.obsidian_paths import relative_markdown_link

    index_path = entities_dir / "index.md"
    lines: list[str] = []

    # Frontmatter
    import yaml
    fm = {
        "source_pdf_id": source_id,
        "entity_type": "entity_index",
        "tags": ["rulebook", "imported", "index"],
    }
    lines.append("---")
    lines.append(yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).strip())
    lines.append("---")
    lines.append("")

    lines.append(f"# Entities — {source_id}")
    lines.append("")
    lines.append(f"**{len(glossary_data)} game terms.**")
    lines.append("")

    # Alphabetical jump navigation
    letters = sorted(set(e["term"][0].upper() for e in glossary_data if e["term"]))
    if letters:
        lines.append("**Jump to:** " + " · ".join(f"[{l}](#{l.lower()})" for l in letters))
        lines.append("")

    # Group by first letter
    current_letter = None
    for entry in glossary_data:  # Already sorted alphabetically
        term = entry["term"]
        source_type = entry.get("source_type", "lexicon")

        first_letter = term[0].upper()
        if first_letter != current_letter:
            current_letter = first_letter
            lines.append(f"## {current_letter}")
            lines.append("")

        slug = entity_slug(term)
        from_path = f"{books_dir}/{source_id}/entities/index.md"
        to_path = f"{books_dir}/{source_id}/entities/{slug}.md"
        link = relative_markdown_link(from_path, to_path, term)

        # Type badge
        type_badge = ""
        if source_type == "lexicon":
            type_badge = " *📖*"
        elif source_type == "inline":
            type_badge = " *📝*"

        lines.append(f"- {link}{type_badge}")
    lines.append("")

    index_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Emitted entities index: {index_path}")


# ── Entity reference rewriting ────────────────────────────────────────


def find_entity_references(
    text: str,
    entity_terms: dict[str, str],
) -> list[tuple[int, str, str]]:
    """Find entity references in text that could be linked to entity pages.

    Scans for occurrences of glossary terms in the text body, excluding
    headings and existing links.

    Args:
        text: The Markdown text to scan.
        entity_terms: Dict of lowercase_term → canonical_term_name.

    Returns:
        List of (position, matched_text, canonical_term) tuples, sorted
        by position ascending.
    """
    results = []
    text_lower = text.lower()

    for term_lower, canonical in sorted(
        entity_terms.items(), key=lambda x: len(x[0]), reverse=True
    ):
        if len(term_lower) <= 2:
            continue

        for m in re.finditer(r'\b' + re.escape(term_lower) + r'\b', text_lower):
            pos = m.start()
            # Check that this isn't inside a Markdown link or heading
            line_start = text.rfind('\n', 0, pos) + 1
            line = text[line_start:text.find('\n', pos)] if text.find('\n', pos) != -1 else text[line_start:]
            line_prefix = text[line_start:pos]

            # Skip if already inside a link [...](...)
            if '[' in line_prefix and ']' not in line_prefix:
                continue
            # Skip if this is a heading line
            if line_prefix.strip().startswith('#'):
                continue
            # Skip if already bold-italic wrapped (likely an original bold definition)
            before = text[max(0, pos-2):pos]
            after = text[m.end():m.end()+2]
            if before.endswith('**') and after.startswith('**'):
                continue

            # Get the actual matched text (preserving original case)
            actual_text = text[pos:pos + len(term_lower)]
            # Check if the matched text has the right word boundaries
            # (may need to check the original text, not lowercase)
            if actual_text.lower() == term_lower:
                results.append((pos, actual_text, canonical))

    return results


def inject_entity_links(
    text: str,
    entity_terms: dict[str, str],
    note_path: str,
    books_dir: str,
    source_id: str,
    max_links_per_section: int = 20,
) -> str:
    """Inject entity links into section text, replacing plain term references
    with Markdown links to entity stub pages.

    For example, if "Dice Pool" is a glossary term, occurrences in the body
    text are replaced with `[Dice Pool](../entities/dice-pool.md)`.

    Uses a two-pass approach: collect all candidate matches first, then
    apply replacements from end-to-start to avoid position shifting.

    Smart avoidance:
    - Terms in headings are never linked
    - Terms already in bold are not re-linked (they're likely definitions)
    - Terms already in a Markdown link are not re-linked
    - Shorter terms that overlap with longer already-matched terms are skipped
    - At most `max_links_per_section` links are injected per section

    Args:
        text: The Markdown text to process.
        entity_terms: Dict of lowercase_term → canonical_term_name.
        note_path: The note's relative path.
        books_dir: The books directory name (usually "books").
        source_id: The PDF source ID.
        max_links_per_section: Maximum number of entity links to inject.

    Returns:
        The text with entity links injected.
    """
    if not entity_terms or not text.strip():
        return text

    from pathlib import PurePosixPath

    # Compute the relative path from this note to the entities/ directory
    note = PurePosixPath(note_path)
    books_prefix = PurePosixPath(books_dir)
    try:
        relative = note.relative_to(books_prefix)
        parts = relative.parts
        if len(parts) >= 2:
            depth = len(parts) - 2
        else:
            depth = 0
    except ValueError:
        depth = len(note.parent.parts)

    # Build the prefix to go from the note to entities/ within the source_id dir
    if depth == 0:
        entities_prefix = "entities/"
    else:
        entities_prefix = "../" * depth + "entities/"

    # Sort terms by length descending to prioritize longer matches first
    # (e.g., "dice pool" before "dice" if both are terms)
    sorted_terms = sorted(
        entity_terms.items(), key=lambda x: len(x[0]), reverse=True
    )

    # ── Pass 1: Collect all candidate matches ──────────────────
    # Each match is (start, end, term_canonical, entity_rel)
    # We track matched regions to avoid overlaps
    matched_regions: list[tuple[int, int]] = []  # (start, end)
    candidates: list[tuple[int, int, str, str]] = []

    text_lower = text.lower()

    for term_lower, canonical in sorted_terms:
        if len(term_lower) <= 2:
            continue
        if len(candidates) >= max_links_per_section:
            break

        slug = entity_slug(canonical)
        entity_rel = f"{entities_prefix}{slug}.md"

        for m in re.finditer(r'\b' + re.escape(term_lower) + r'\b', text_lower):
            pos = m.start()
            end_pos = m.end()

            # Check for overlap with already-matched regions
            overlaps = False
            for rstart, rend in matched_regions:
                if pos < rend and end_pos > rstart:
                    overlaps = True
                    break
            if overlaps:
                continue

            # Check that this isn't inside a Markdown link or heading
            line_start = text.rfind('\n', 0, pos) + 1
            line_prefix = text[line_start:pos]

            # Skip if already inside a link [...](...)
            if '[' in line_prefix and ']' not in line_prefix:
                continue
            # Skip if this is a heading line
            if line_prefix.strip().startswith('#'):
                continue
            # Skip if already bold-wrapped
            before = text[max(0, pos-2):pos]
            after = text[end_pos:end_pos+2]
            if before.endswith('**') and after.startswith('**'):
                continue
            # Skip if preceded by '(' — inside link target ](...
            preceding = text[max(0, pos-50):pos]
            if ']' in preceding and '(' in preceding[preceding.rfind(']'):]:
                continue

            # Verify the actual text matches
            actual_text = text[pos:end_pos]
            if actual_text.lower() != term_lower:
                continue

            # Valid candidate
            matched_regions.append((pos, end_pos))
            candidates.append((pos, end_pos, canonical, entity_rel))

            if len(candidates) >= max_links_per_section:
                break

    if not candidates:
        return text

    # ── Pass 2: Apply replacements from end to start ────────────
    # Processing in reverse order avoids position shifting
    candidates.sort(key=lambda c: c[0], reverse=True)

    for pos, end_pos, canonical, entity_rel in candidates:
        actual_text = text[pos:end_pos]
        replacement = f"[{actual_text}]({entity_rel})"
        text = text[:pos] + replacement + text[end_pos:]

    logger.debug(f"Injected {len(candidates)} entity links in {note_path}")
    return text
