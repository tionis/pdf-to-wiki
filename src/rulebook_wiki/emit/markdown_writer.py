"""Markdown skeleton emission — generate Obsidian-friendly Markdown files from the section tree.

This is a deterministic operation; no LLM is involved.

Each generated note includes:
- YAML frontmatter with source and page metadata
- Title heading
- Extracted text content (if available) or a placeholder
"""

from __future__ import annotations

from datetime import datetime, timezone

import yaml

from rulebook_wiki.cache.artifact_store import ArtifactStore
from rulebook_wiki.cache.db import CacheDB
from rulebook_wiki.cache.manifests import StepManifestStore
from rulebook_wiki.config import WikiConfig
from rulebook_wiki.emit.obsidian_paths import section_note_path
from rulebook_wiki.logging import get_logger
from rulebook_wiki.models import ProvenanceRecord, SectionNode, SectionTree

logger = get_logger(__name__)


def emit_skeleton(
    source_id: str,
    config: WikiConfig,
    force: bool = False,
    force_step: str | None = None,
) -> dict[str, str]:
    """Emit Markdown skeleton files from the cached section tree.

    If extracted text is available (from the extract step), it will be
    included in each section's note body. Otherwise, a placeholder is used.

    Returns a dict mapping section_id → relative output path.
    """
    db = CacheDB(config.resolved_cache_db_path())
    artifacts = ArtifactStore(config.resolved_artifact_dir())
    manifests = StepManifestStore(db)

    source = db.get_pdf_source(source_id)
    if source is None:
        raise ValueError(f"No registered PDF with source_id={source_id!r}. Run 'register' first.")

    step = "emit_skeleton"

    # Check cache
    should_force = force or (force_step == step)
    if not should_force and manifests.is_completed(source_id, step):
        cached = artifacts.load_json(source_id, "emit_manifest")
        if cached is not None:
            logger.info(f"Skeleton for {source_id} already emitted. Use --force to re-emit.")
            db.close()
            return cached

    manifests.mark_running(source_id, step)

    # Load section tree
    tree_data = artifacts.load_json(source_id, "section_tree")
    if tree_data is None:
        raise ValueError(f"No section tree for {source_id}. Run 'build-section-tree' first.")
    tree = SectionTree(**tree_data)

    # Load extracted text if available
    extracted_text: dict[str, str] | None = artifacts.load_json(source_id, "extract_text")
    if extracted_text is not None:
        logger.info(f"Loaded extracted text for {len(extracted_text)} sections")
    else:
        logger.info("No extracted text found; notes will use placeholders")

    # Generate Markdown files
    output_dir = config.resolved_output_dir()
    emit_manifest: dict[str, str] = {}

    for section_id, node in tree.nodes.items():
        rel_path = section_note_path(node, tree, config.books_dir)
        abs_path = output_dir / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        section_text = extracted_text.get(section_id, "") if extracted_text else ""
        # Apply repair/normalization to extracted text
        if section_text and section_text.strip():
            from rulebook_wiki.repair.normalize import repair_text
            section_text = repair_text(section_text, tree)
        content = _render_note(node, tree, source.path, section_text)
        abs_path.write_text(content, encoding="utf-8")

        # Update node's markdown_output_path
        node.markdown_output_path = rel_path
        emit_manifest[section_id] = rel_path

        logger.debug(f"Emitted {abs_path}")

    # Save updated tree (with output paths)
    artifacts.save_json(source_id, "section_tree", tree.model_dump())

    # Save emit manifest
    artifacts.save_json(source_id, "emit_manifest", emit_manifest)

    # Generate book-level index if configured
    if config.obsidian_emit_index_notes:
        _emit_book_index(tree, source, output_dir, config.books_dir)

    now = datetime.now(timezone.utc).isoformat()
    prov = ProvenanceRecord(
        artifact_id=f"{source_id}/emit_skeleton",
        source_id=source_id,
        step=step,
        tool="rulebook_wiki",
        tool_version="0.1.0",
        config_hash="",
        created_at=now,
    )
    db.insert_provenance(prov)
    manifests.mark_completed(source_id, step, artifact_path=f"{source_id}/emit_manifest.json")

    logger.info(f"Emitted {len(emit_manifest)} Markdown notes for {source_id}")
    db.close()
    return emit_manifest


def _render_note(node: SectionNode, tree: SectionTree, source_pdf_path: str, extracted_text: str = "") -> str:
    """Render a single Markdown note for a section node.

    If extracted_text is non-empty, it is included as the note body.
    Otherwise, a placeholder is used.
    """
    # Frontmatter
    fm = {
        "source_pdf": str(source_pdf_path),
        "source_pdf_id": node.source_id,
        "section_id": node.section_id,
        "level": node.level,
        "pdf_page_start": node.pdf_page_start,
        "pdf_page_end": node.pdf_page_end,
        "parent_section_id": node.parent_id or None,
        "aliases": [],
        "tags": ["rulebook", "imported"],
    }

    # Only include printed page labels when they exist
    if node.printed_page_start is not None:
        fm["printed_page_start"] = node.printed_page_start
    if node.printed_page_end is not None:
        fm["printed_page_end"] = node.printed_page_end

    # YAML frontmatter block
    fm_lines = ["---"]
    fm_lines.append(yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).strip())
    fm_lines.append("---")
    fm_block = "\n".join(fm_lines)

    # Title heading (H1)
    heading = f"# {node.title}"

    # Body: use extracted text or placeholder
    if extracted_text and extracted_text.strip():
        body = extracted_text.strip()
        # Deduplicate: if the extracted text starts with a heading that
        # matches the section title, remove the duplicate heading.
        # Marker often produces "# *Damage*" when our heading is "# Damage".
        body = _deduplicate_heading(body, node.title)
    else:
        body = "> Content extraction not yet populated."

    return f"{fm_block}\n\n{heading}\n\n{body}\n"


def emit_global_index(config: WikiConfig) -> None:
    """Emit a global wiki index linking to all registered books."""
    from rulebook_wiki.cache.db import CacheDB
    from rulebook_wiki.models import PdfSource

    db = CacheDB(config.resolved_cache_db_path())
    artifacts = ArtifactStore(config.resolved_artifact_dir())

    sources = db.list_pdf_sources()
    db.close()

    if not sources:
        return

    output_dir = config.resolved_output_dir()
    index_path = output_dir / config.books_dir / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Rulebook Wiki",
        "",
        f"**{len(sources)} book{'s' if len(sources) != 1 else ''} in the library.**",
        "",
        "## Books",
        "",
    ]

    for source in sources:
        # Check if section tree exists
        tree_data = artifacts.load_json(source.source_id, "section_tree")
        chapter_count = 0
        if tree_data:
            tree = SectionTree(**tree_data)
            chapter_count = len(tree.root_ids)

        link_slug = f"{config.books_dir}/{source.source_id}"
        desc = f"{source.page_count} pages"
        if chapter_count:
            desc += f", {chapter_count} chapters"
        if source.title:
            lines.append(f"- [[{link_slug}|{source.title}]] — {desc}")
        else:
            lines.append(f"- [[{link_slug}|{source.source_id}]] — {desc}")

    lines.append("")

    index_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Emitted global wiki index: {index_path}")


def _deduplicate_heading(body: str, section_title: str) -> str:
    """Remove a leading heading from body text if it duplicates the section title.

    When Marker extracts a section, its Markdown often begins with a heading
    like '# *Damage*' while our emitted heading is '# Damage'. This produces
    duplicate headings. We strip the Marker heading if it matches.
    """
    import re

    # Normalize: strip Markdown formatting chars for comparison
    title_clean = re.sub(r"[*_`\[\]()#]", "", section_title).strip().lower()

    # Check if the first non-blank line is a heading
    lines = body.split("\n")
    first_content_idx = 0
    while first_content_idx < len(lines) and not lines[first_content_idx].strip():
        first_content_idx += 1

    if first_content_idx >= len(lines):
        return body

    first_line = lines[first_content_idx]
    m = re.match(r"^(#{1,6})\s+(.+)$", first_line)
    if not m:
        return body

    heading_text = re.sub(r"[*_`\[\]()]", "", m.group(2)).strip().lower()

    # Check match: exact, prefix, or substring (with minimum length)
    is_match = (
        heading_text == title_clean
        or heading_text.startswith(title_clean)
        or title_clean.startswith(heading_text)
    )
    # Also check if one contains the other with decent overlap
    if not is_match and len(title_clean) >= 4 and len(heading_text) >= 4:
        if title_clean in heading_text or heading_text in title_clean:
            is_match = True

    if is_match:
        # Remove the heading line and any blank line after it
        end_idx = first_content_idx + 1
        while end_idx < len(lines) and not lines[end_idx].strip():
            end_idx += 1
        return "\n".join(lines[end_idx:]).strip()

    return body


def _emit_book_index(
    tree: SectionTree,
    source: "PdfSource",  # noqa: F821
    output_dir: Path,
    books_dir: str,
) -> None:
    """Emit a top-level index.md for the book."""
    from rulebook_wiki.models import PdfSource

    index_path = output_dir / books_dir / tree.source_id / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    fm = {
        "source_pdf": source.path,
        "source_pdf_id": source.source_id,
        "section_id": f"{tree.source_id}",
        "level": 0,
        "pdf_page_start": 0,
        "pdf_page_end": max(n.pdf_page_end for n in tree.nodes.values()) if tree.nodes else 0,
        "aliases": [],
        "tags": ["rulebook", "imported", "index"],
    }

    fm_lines = ["---"]
    fm_lines.append(yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).strip())
    fm_lines.append("---")

    lines = ["\n".join(fm_lines), ""]
    lines.append(f"# {source.title or tree.source_id}")
    lines.append("")
    lines.append(f"**Pages:** {source.page_count}")
    lines.append(f"**SHA-256:** `{source.sha256[:16]}…`")
    lines.append("")

    # List top-level sections
    if tree.root_ids:
        lines.append("## Chapters")
        lines.append("")
        for rid in tree.root_ids:
            node = tree.nodes[rid]
            # Obsidian wiki-link: section_note_path already includes /index.md for parent nodes
            link_slug = section_note_path(node, tree, books_dir).replace(".md", "")
            lines.append(f"- [[{link_slug}|{node.title}]]")
        lines.append("")

    index_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Emitted book index: {index_path}")