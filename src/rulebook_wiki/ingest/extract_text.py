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

from rulebook_wiki.cache.artifact_store import ArtifactStore
from rulebook_wiki.cache.db import CacheDB
from rulebook_wiki.cache.manifests import StepManifestStore
from rulebook_wiki.config import WikiConfig
from rulebook_wiki.extract import get_engine, list_engines
# Import engines to trigger registration
import rulebook_wiki.extract.pymupdf_engine  # noqa: F401
import rulebook_wiki.extract.marker_engine  # noqa: F401
from rulebook_wiki.logging import get_logger
from rulebook_wiki.models import ProvenanceRecord, SectionTree

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

    # Extract text per section — strategy varies by engine
    if engine_name == "marker":
        extracted = _extract_with_marker(source, tree, engine_instance, config)
    else:
        extracted = {}
        for section_id, node in tree.nodes.items():
            text = engine_instance.extract_page_range(
                source.path, node.pdf_page_start, node.pdf_page_end
            )
            extracted[section_id] = text

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
    3. Split the Markdown into per-section content by matching
       section titles to heading anchors

    This approach is O(N_pages) total rather than O(N_pages * N_sections).
    """
    from rulebook_wiki.cache.artifact_store import ArtifactStore
    from rulebook_wiki.extract.marker_engine import MarkerEngine, split_markdown_by_headings

    assert isinstance(engine, MarkerEngine)

    # Check for cached full-PDF Marker output
    artifacts = ArtifactStore(config.resolved_artifact_dir())
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
    sections: list[tuple[str, str, int, int]] = []
    for section_id, node in tree.nodes.items():
        sections.append((section_id, node.title, node.pdf_page_start, node.pdf_page_end))

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
        from rulebook_wiki.extract import get_engine
        pymupdf = get_engine("pymupdf", config)
        for section_id in missing:
            node = tree.nodes[section_id]
            text = pymupdf.extract_page_range(source.path, node.pdf_page_start, node.pdf_page_end)
            extracted[section_id] = text

    return extracted