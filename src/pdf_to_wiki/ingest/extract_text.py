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
        from pdf_to_wiki.extract import get_engine
        pymupdf = get_engine("pymupdf", config)
        for section_id in missing:
            node = tree.nodes[section_id]
            text = pymupdf.extract_page_range(source.path, node.pdf_page_start, node.pdf_page_end)
            extracted[section_id] = text

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