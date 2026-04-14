"""Text extraction from PDF — dispatches to pluggable extraction engines.

The extraction step pulls text content from the PDF for each section's
page range. The engine used is determined by the ``extract_engine``
config setting (default: "marker").

Available engines:
  - "marker": ML-powered extraction via marker-pdf (high quality,
    handles columns/tables/images, requires ~2GB model download)
  - "pymupdf": Deterministic extraction via PyMuPDF dict mode
    (no models, decent quality, may have column issues)

Results are cached as JSON artifacts. The step is resumable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath

from pdf_to_wiki.cache.artifact_store import ArtifactStore
from pdf_to_wiki.cache.db import CacheDB
from pdf_to_wiki.cache.manifests import StepManifestStore
from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.extract import get_engine, list_engines
# Import engines to trigger registration
import pdf_to_wiki.extract.pymupdf_engine  # noqa: F401
import pdf_to_wiki.extract.marker_engine  # noqa: F401
from pdf_to_wiki.logging import get_logger
from pdf_to_wiki.models import ProvenanceRecord, SectionTree

logger = get_logger(__name__)


def extract_text(
    source_id: str,
    config: WikiConfig,
    force: bool = False,
    engine: str | None = None,
) -> dict[str, str]:
    """Extract text content from the PDF for each section's page range.

    Uses the configured extraction engine (default: marker).
    Results are cached as JSON artifacts.

    Args:
        source_id: The registered PDF source ID.
        config: Pipeline configuration.
        force: Force re-extraction even if cached.
        engine: Override the configured extraction engine.

    Returns:
        Dict mapping section_id → extracted text content.
    """
    db = CacheDB(config.resolved_cache_db_path())
    artifacts = ArtifactStore(config.resolved_artifact_dir())
    manifests = StepManifestStore(db)

    source = db.get_pdf_source(source_id)
    if source is None:
        raise ValueError(f"No registered PDF with source_id={source_id!r}. Run 'register' first.")

    # Check cache
    if not force and manifests.is_completed(source_id, "extract_text"):
        cached = artifacts.load_json(source_id, "extract_text")
        if cached is not None:
            logger.info(f"Text extraction for {source_id} already cached. Use --force to re-extract.")
            db.close()
            return cached

    # Resolve engine
    engine_name = engine or config.extract_engine
    available = list_engines()
    if engine_name not in available:
        logger.warning(
            f"Engine {engine_name!r} not available (available: {', '.join(available)}). "
            f"Falling back to 'pymupdf'."
        )
        engine_name = "pymupdf"

    engine_instance = get_engine(engine_name, config)
    logger.info(f"Using extraction engine: {engine_instance.engine_name} v{engine_instance.engine_version}")

    manifests.mark_running(source_id, "extract_text")

    # Load section tree
    tree_data = artifacts.load_json(source_id, "section_tree")
    if tree_data is None:
        raise ValueError(f"No section tree for {source_id}. Run 'build-section-tree' first.")
    tree = SectionTree(**tree_data)

    # Extract text per section —
    # strategy varies by engine
    if engine_name == "marker":
        extracted = _extract_with_marker(source, tree, engine_instance, config)
    else:
        # Pre-compute which sections share a start page with a sibling
        # (used to pass start_heading for mid-page extraction)
        overlap_sections = _find_overlapping_siblings(tree)

        extracted = {}
        for section_id, node in tree.nodes.items():
            # Clip parent sections to only include pages before first child
            end_page = node.pdf_page_end
            if node.children:
                first_child_start = min(
                    tree.nodes[cid].pdf_page_start for cid in node.children
                )
                end_page = min(end_page, max(first_child_start - 1, node.pdf_page_start))

            # If this section shares a start page with a sibling,
            # pass the section title as start_heading so the engine
            # can extract only from the heading onwards on the first page
            start_heading = None
            if section_id in overlap_sections:
                start_heading = node.title

            text = engine_instance.extract_page_range(
                source.path, node.pdf_page_start, end_page,
                start_heading=start_heading,
            )
            extracted[section_id] = text

    # Extract images from PDF and rewrite references
    image_map = _extract_images(source, config)
    if image_map:
        from pdf_to_wiki.extract.pdf_images import rewrite_image_refs_in_sections
        extracted = rewrite_image_refs_in_sections(extracted, image_map)

    # Extract dingbat font manifest for repair pipeline
    _extract_dingbats(source, config)

    # Persist
    artifacts.save_json(source_id, "extract_text", extracted)

    now = datetime.now(timezone.utc).isoformat()
    prov = ProvenanceRecord(
        artifact_id=f"{source_id}/extract_text",
        source_id=source_id,
        step="extract_text",
        tool=engine_instance.engine_name,
        tool_version=engine_instance.engine_version,
        config_hash="",
        created_at=now,
    )
    db.insert_provenance(prov)
    manifests.mark_completed(source_id, "extract_text", artifact_path=f"{source_id}/extract_text.json")

    total_chars = sum(len(t) for t in extracted.values())
    non_empty = sum(1 for t in extracted.values() if t.strip())
    logger.info(
        f"Extracted text for {source_id}: {non_empty}/{len(extracted)} sections have content, "
        f"{total_chars:,} total characters"
    )
    db.close()
    return extracted


def _extract_with_marker(source, tree: SectionTree, engine, config: WikiConfig) -> dict[str, str]:
    """Extract text using Marker with a full-PDF-then-split strategy.

    Marker's per-call overhead is high (model inference per page), so we:

    1. Convert the entire PDF in a single Marker call
    2. Cache the raw full-PDF Markdown
    3. Cache the extracted images as PNG files in the artifact store
    4. Split the Markdown into per-section content by matching
       section titles to heading anchors
    5. Save images to the wiki output directory and rewrite refs

    This approach is O(N_pages) total rather than O(N_pages * N_sections).
    """
    from pathlib import Path
    from pdf_to_wiki.cache.artifact_store import ArtifactStore
    from pdf_to_wiki.extract.marker_engine import MarkerEngine, split_markdown_by_headings

    assert isinstance(engine, MarkerEngine)

    artifacts = ArtifactStore(config.resolved_artifact_dir())

    # Check for cached full-PDF Marker output
    full_md = artifacts.load_text(source.source_id, "marker_full_md", suffix=".md")

    if full_md is None:
        logger.info("Running Marker full-PDF conversion (one-time, cached after)...")
        full_md = engine.extract_full_pdf(source.path)

        # Cache the raw markdown for reuse
        artifacts.save_text(source.source_id, "marker_full_md", full_md, suffix=".md")
        logger.info(f"Marker full-PDF conversion complete: {len(full_md):,} chars cached")
    else:
        logger.info(f"Using cached Marker output: {len(full_md):,} chars")

    # Build section list for heading matching
    # For parent sections (with children), clip the end page to just
    # before the first child's start page. This prevents parents from
    # duplicating all their children's content.
    sections: list[tuple[str, str, int, int]] = []
    for section_id, node in tree.nodes.items():
        end_page = node.pdf_page_end
        if node.children:
            first_child_start = min(
                tree.nodes[cid].pdf_page_start for cid in node.children
            )
            end_page = min(end_page, max(first_child_start - 1, node.pdf_page_start))
        sections.append((section_id, node.title, node.pdf_page_start, end_page))

    # Split the markdown by headings
    logger.info(f"Splitting Marker output into {len(sections)} sections by headings...")
    extracted = split_markdown_by_headings(full_md, sections)

    # For sections that didn't get heading-matched text, fall back to
    # per-page extraction using PyMuPDF (fast, no ML needed)
    missing = [sid for sid, text in extracted.items() if not text.strip()]
    if missing:
        logger.info(
            f"Sections without heading matches: {len(missing)}, "
            f"falling back to PyMuPDF for those"
        )
        from pdf_to_wiki.extract import get_engine
        pymupdf = get_engine("pymupdf", config)
        for section_id in missing:
            node = tree.nodes[section_id]
            # Clip parent sections to only include pages before first child
            end_page = node.pdf_page_end
            if node.children:
                first_child_start = min(
                    tree.nodes[cid].pdf_page_start for cid in node.children
                )
                end_page = min(end_page, max(first_child_start - 1, node.pdf_page_start))
            text = pymupdf.extract_page_range(source.path, node.pdf_page_start, end_page)
            extracted[section_id] = text

    return extracted


def _find_overlapping_siblings(tree: SectionTree) -> set[str]:
    """Find section IDs that share a start page with a sibling.

    These sections may start mid-page, so their text extraction
    should include a start_heading to skip content before the heading.
    """
    # Group siblings by parent
    parent_children: dict[str | None, list[str]] = {}
    for section_id, node in tree.nodes.items():
        if node.parent_id not in parent_children:
            parent_children[node.parent_id] = []
        parent_children[node.parent_id].append(section_id)

    overlap = set()
    for parent_id, child_ids in parent_children.items():
        if len(child_ids) < 2:
            continue
        for i in range(len(child_ids) - 1):
            node_i = tree.nodes[child_ids[i]]
            node_j = tree.nodes[child_ids[i + 1]]
            if node_i.pdf_page_start == node_j.pdf_page_start:
                overlap.add(child_ids[i])
                overlap.add(child_ids[i + 1])

    return overlap


def _split_overlapping_sections(
    extracted: dict[str, str], tree: SectionTree,
) -> dict[str, str]:
    """Trim prefix pollution from sections that share a start page.

    When two sibling sections start on the same page, PyMuPDF gives
    both of them the entire page — including content from previous
    sections that appears before the heading on that page.

    We fix this by trimming each affected section's text to start at
    its OWN heading. We ONLY trim the prefix (content before the
    heading). The section keeps all content from the heading onward
    through its full page range — multi-page sections are never
    truncated.

    This only applies to sections that share a start page with a
    sibling — it does NOT aggressively trim all sections.
    """
    import re

    # Group siblings by parent
    parent_children: dict[str | None, list[str]] = {}
    for section_id, node in tree.nodes.items():
        if node.parent_id not in parent_children:
            parent_children[node.parent_id] = []
        parent_children[node.parent_id].append(section_id)

    # Collect section IDs that share a start page with a sibling
    needs_trim = set()
    for parent_id, child_ids in parent_children.items():
        if len(child_ids) < 2:
            continue
        for i in range(len(child_ids) - 1):
            node_i = tree.nodes[child_ids[i]]
            node_j = tree.nodes[child_ids[i + 1]]
            if node_i.pdf_page_start == node_j.pdf_page_start:
                needs_trim.add(child_ids[i])
                needs_trim.add(child_ids[i + 1])

    if not needs_trim:
        return extracted

    # Trim prefix from overlapping sections only
    trimmed = 0
    for section_id in needs_trim:
        text = extracted.get(section_id, "")
        if not text or len(text) < 50:
            continue
        node = tree.nodes[section_id]

        heading_pattern = (
            r"^#{0,3}\s*\*{0,2}"
            + re.escape(node.title)
            + r"\*{0,2}\s*$"
        )

        matches = list(re.finditer(heading_pattern, text, re.MULTILINE | re.IGNORECASE))
        if not matches:
            continue

        first_match = matches[0]
        lines_before = text[:first_match.start()].count('\n')
        if lines_before <= 1:
            continue  # Already starts at or near the heading

        # Trim: keep everything from the first heading match onwards.
        # This preserves all multi-page content after the heading.
        trimmed_text = text[first_match.start():].strip()
        if len(trimmed_text) >= 50:
            extracted[section_id] = trimmed_text
            trimmed += 1
            logger.debug(
                f"Trimmed '{node.title}' to start at own heading "
                f"(removed {lines_before} lines of preceding content)"
            )

    if trimmed:
        logger.info(f"Trimmed {trimmed} overlapping sections to start at their own headings")

    return extracted


def _extract_images(source, config: WikiConfig) -> dict[str, str]:
    """Extract images from the PDF and save them to the wiki assets dir.

    Uses PyMuPDF to extract images from each page (fast, no ML needed).
    Returns a dict mapping Marker-style filenames to wiki-root-relative paths.
    Caches the image map for reuse.
    """
    from pathlib import Path
    from pdf_to_wiki.cache.artifact_store import ArtifactStore
    from pdf_to_wiki.extract.pdf_images import extract_pdf_images

    artifacts = ArtifactStore(config.resolved_artifact_dir())
    output_dir = config.resolved_output_dir()

    # Check for cached image map
    cached_images = artifacts.load_json(source.source_id, "pdf_images")
    if cached_images:
        # Verify at least one referenced image still exists.
        # Images are stored in books/source_id/.assets/ but the image_map
        # keys use wiki-root-relative paths (assets/source_id/...) for
        # compatibility with _rewrite_asset_paths(). Validate by checking
        # the actual file location.
        assets_dir = output_dir / config.books_dir / source.source_id / ".assets"
        some_exist = any(
            (assets_dir / PurePosixPath(p).name).exists()
            for p in cached_images.values()
        )
        if some_exist:
            logger.info(f"Using cached image map: {len(cached_images)} images")
            return cached_images

    # Extract images from PDF
    image_map = extract_pdf_images(source.path, source.source_id, output_dir, books_dir=config.books_dir)

    # Cache the mapping
    if image_map:
        artifacts.save_json(source.source_id, "pdf_images", image_map)

    return image_map


def _extract_dingbats(source, config: WikiConfig) -> dict[str, list[str]]:
    """Extract dingbat font manifest from the PDF.

    Scans the PDF with PyMuPDF to find characters from dingbat/symbol fonts
    and builds a replacement mapping. Caches the manifest for reuse.

    Returns:
        Dict mapping dingbat characters to their replacement character list.
        E.g., {"Y": ["\u2022"]}
    """
    from pdf_to_wiki.cache.artifact_store import ArtifactStore
    from pdf_to_wiki.repair.clean_text import extract_dingbat_manifest

    artifacts = ArtifactStore(config.resolved_artifact_dir())

    # Check for cached manifest
    cached = artifacts.load_json(source.source_id, "dingbat_manifest")
    if cached is not None:
        return cached

    # Build manifest from PDF
    manifest = extract_dingbat_manifest(source.path)

    # Cache it
    if manifest:
        artifacts.save_json(source.source_id, "dingbat_manifest", manifest)

    return manifest