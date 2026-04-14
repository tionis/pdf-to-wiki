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

from pdf_to_wiki.cache.artifact_store import ArtifactStore
from pdf_to_wiki.cache.db import CacheDB
from pdf_to_wiki.cache.manifests import StepManifestStore
from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.emit.obsidian_paths import section_note_path, relative_markdown_link
from pdf_to_wiki.logging import get_logger
from pdf_to_wiki.models import ProvenanceRecord, SectionNode, SectionTree

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

    # Load dingbat manifest for repair pipeline (if available)
    dingbat_manifest = artifacts.load_json(source_id, "dingbat_manifest")

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
            from pdf_to_wiki.repair.normalize import repair_text
            section_text = repair_text(section_text, tree, current_note_path=rel_path, dingbat_manifest=dingbat_manifest)
        # Rewrite wiki-root-relative image refs to note-relative paths
        if section_text and "assets/" in section_text:
            section_text = _rewrite_asset_paths(section_text, rel_path, config.books_dir, source_id=tree.source_id)
        content = _render_note(node, tree, source.path, source.sha256, section_text)
        abs_path.write_text(content, encoding="utf-8")

        # Update node's markdown_output_path
        node.markdown_output_path = rel_path
        emit_manifest[section_id] = rel_path

        logger.debug(f"Emitted {abs_path}")

    # Save updated tree (with output paths)
    artifacts.save_json(source_id, "section_tree", tree.model_dump())

    # Remove stale files from previous emission
    _cleanup_stale_files(source_id, emit_manifest, artifacts, output_dir, config)

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
        tool="pdf_to_wiki",
        tool_version="0.1.0",
        config_hash="",
        created_at=now,
    )
    db.insert_provenance(prov)
    manifests.mark_completed(source_id, step, artifact_path=f"{source_id}/emit_manifest.json")

    logger.info(f"Emitted {len(emit_manifest)} Markdown notes for {source_id}")
    db.close()
    return emit_manifest


def _cleanup_stale_files(
    source_id: str,
    new_manifest: dict[str, str],
    artifacts: "ArtifactStore",
    output_dir: Path,
    config: WikiConfig,
) -> None:
    """Remove files from a previous emission that are no longer in the manifest.

    Compares the new manifest against the previously saved one and
    deletes any files that existed before but are not in the current
    manifest. This handles cases where sections were renamed, merged,
    or removed from the section tree between runs.

    Also removes empty directories left behind after file deletion.
    """
    old_manifest = artifacts.load_json(source_id, "emit_manifest")
    if old_manifest is None:
        logger.debug("No previous manifest found, skipping stale file cleanup")
        return

    old_paths = set(old_manifest.values())
    new_paths = set(new_manifest.values())
    stale_paths = old_paths - new_paths

    if not stale_paths:
        logger.debug("No stale files to clean up")
        return

    removed = 0
    for rel_path in sorted(stale_paths):
        abs_path = output_dir / rel_path
        if abs_path.exists():
            abs_path.unlink()
            removed += 1
            logger.debug(f"Removed stale file: {rel_path}")
            # If this was an index.md, also check for empty parent directory
            if rel_path.endswith("/index.md"):
                parent = abs_path.parent
                try:
                    parent.rmdir()  # Only removes if empty
                    logger.debug(f"Removed empty directory: {parent}")
                except OSError:
                    pass  # Directory not empty, leave it
        else:
            logger.debug(f"Stale file already gone: {rel_path}")

    if removed:
        logger.info(f"Cleaned up {removed} stale file{'s' if removed != 1 else ''} from previous emission")


def _render_note(node: SectionNode, tree: SectionTree, source_pdf_path: str, source_sha256: str, extracted_text: str = "") -> str:
    """Render a single Markdown note for a section node.

    If extracted_text is non-empty, it is included as the note body.
    Otherwise, a placeholder is used.
    """
    # Generate a portable source reference: filename + hash prefix
    # instead of absolute path which isn't portable across machines
    import os
    pdf_filename = os.path.basename(str(source_pdf_path))
    source_ref = f"{pdf_filename} (sha256:{source_sha256[:16]})"

    # Frontmatter
    fm = {
        "source_pdf": source_ref,
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
    from pdf_to_wiki.cache.db import CacheDB
    from pdf_to_wiki.models import PdfSource

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

        # Global index is at books/index.md
        # Book index is at books/source_id/index.md
        from_note_path = f"{config.books_dir}/index.md"
        to_note_path = f"{config.books_dir}/{source.source_id}/index.md"
        book_title = source.title or source.source_id
        link = relative_markdown_link(from_note_path, to_note_path, book_title)
        desc = f"{source.page_count} pages"
        if chapter_count:
            desc += f", {chapter_count} chapters"
        lines.append(f"- {link} — {desc}")

    lines.append("")

    index_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Emitted global wiki index: {index_path}")


def _deduplicate_heading(body: str, section_title: str) -> str:
    """Remove headings from body text that duplicate the section title.

    When Marker extracts a section, its Markdown often begins with a heading
    like '# *Damage*' while our emitted heading is '# Damage'. This produces
    duplicate headings. We strip leading Marker heading(s) that match.

    Marker sometimes outputs the same section heading twice in a row
    (e.g., once above a table, once above body text after a heading merge).
    All consecutive matching headings at the start are stripped, and any
    subsequent heading that exactly matches the section title is also removed
    to avoid duplicate H1 headings in the rendered output.
    """
    import re

    title_clean = re.sub(r"[*_`\[\]()#]", "", section_title).strip().lower()

    lines = body.split("\n")
    result_lines: list[str] = []

    # First pass: strip all consecutive leading headings that match
    idx = 0
    while idx < len(lines):
        stripped = lines[idx].strip()
        if not stripped:
            result_lines.append(lines[idx])
            idx += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.+)$", lines[idx])
        if not m:
            break  # Non-heading content — stop leading stripping

        heading_text = re.sub(r"[*_`\[\]()]", "", m.group(2)).strip().lower()
        is_match = (
            heading_text == title_clean
            or heading_text.startswith(title_clean)
            or title_clean.startswith(heading_text)
        )
        if not is_match and len(title_clean) >= 4 and len(heading_text) >= 4:
            if title_clean in heading_text or heading_text in title_clean:
                is_match = True

        if not is_match:
            break  # Non-matching heading — stop leading stripping

        # Strip this heading line
        idx += 1
        # Also skip blank line after stripped heading
        while idx < len(lines) and not lines[idx].strip():
            idx += 1

    # Second pass: collect remaining lines, removing duplicate title headings
    while idx < len(lines):
        stripped = lines[idx].strip()
        if stripped:
            m = re.match(r"^(#{1,6})\s+(.+)$", lines[idx])
            if m:
                heading_text = re.sub(r"[*_`\[\]()]", "", m.group(2)).strip().lower()
                is_match = (
                    heading_text == title_clean
                    or heading_text.startswith(title_clean)
                    or title_clean.startswith(heading_text)
                )
                if not is_match and len(title_clean) >= 4 and len(heading_text) >= 4:
                    if title_clean in heading_text or heading_text in title_clean:
                        is_match = True
                if is_match:
                    # Skip this duplicate heading and any blank line after it
                    idx += 1
                    while idx < len(lines) and not lines[idx].strip():
                        idx += 1
                    continue
        result_lines.append(lines[idx])
        idx += 1

    text = "\n".join(result_lines).strip()
    return text if text else body


def _rewrite_asset_paths(text: str, note_path: str, books_dir: str, source_id: str) -> str:
    """Rewrite wiki-root-relative asset paths to note-relative paths.

    Image references like `![](assets/source_id/img.png)` are wiki-root-relative.
    Since assets are stored in `books/source_id/.assets/`, this function
    rewrites references to use the note-relative path to `.assets/`.

    For example, from `books/source_id/chapter/section.md`:
      assets/source_id/img.png → ../.assets/img.png

    From `books/source_id/index.md`:
      assets/source_id/img.png → .assets/img.png
    """
    import re
    from pathlib import PurePosixPath

    # Compute depth: how many directories deep is this note?
    # e.g., books/source_id/chapter/section.md → 2 levels deep below source_id
    #       books/source_id/index.md → 0 levels deep below source_id
    note = PurePosixPath(note_path)
    books_prefix = PurePosixPath(books_dir)
    try:
        relative = note.relative_to(books_prefix)
        # Parts relative to books/: source_id/chapter/section.md
        # Depth below source_id = len(parts) - 2 (skip source_id and filename)
        parts = relative.parts
        # If parts = (source_id, chapter, section.md), depth = len(parts) - 2
        # If parts = (source_id, index.md), depth = 0
        if len(parts) >= 2:
            depth = len(parts) - 2  # depth below source_id directory
        else:
            depth = 0
    except ValueError:
        depth = len(note.parent.parts)

    # The prefix to go from note to .assets/ within the source_id dir
    if depth == 0:
        prefix = ".assets/"
    else:
        prefix = "../" * depth + ".assets/"

    def _replace(m):
        alt_text = m.group(1)
        img_path = m.group(2)
        # Only rewrite wiki-root-relative paths
        if img_path.startswith("assets/"):
            # Extract just the filename (drop assets/source_id/ prefix)
            # assets/source_id/page_N_picture_X.png → page_N_picture_X.png
            path_parts = PurePosixPath(img_path)
            if len(path_parts.parts) >= 3:
                # Skip assets/ and source_id/ — just keep the filename
                filename = path_parts.name
                return f"![{alt_text}]({prefix}{filename})"
            else:
                return f"![{alt_text}]({prefix}{img_path})"
        return m.group(0)

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _replace, text)


def _emit_book_index(
    tree: SectionTree,
    source: "PdfSource",  # noqa: F821
    output_dir: Path,
    books_dir: str,
) -> None:
    """Emit a top-level index.md for the book."""
    from pdf_to_wiki.models import PdfSource
    import os

    index_path = output_dir / books_dir / tree.source_id / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    fm = {
        "source_pdf": f"{os.path.basename(source.path)} (sha256:{source.sha256[:16]})",
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

    # List top-level sections with page ranges for context
    if tree.root_ids:
        lines.append("## Chapters")
        lines.append("")
        # The index is at books/source_id/index.md — links are relative from there
        index_note_path = f"{books_dir}/{tree.source_id}/index.md"
        for rid in tree.root_ids:
            node = tree.nodes[rid]
            target_path = section_note_path(node, tree, books_dir)
            link = relative_markdown_link(index_note_path, target_path, node.title)
            lines.append(f"- {link}")
        lines.append("")

    index_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Emitted book index: {index_path}")