"""Import BlobForge conversion output into the pdf-to-wiki pipeline.

BlobForge (https://github.com/tionis/blobforge) runs Marker on distributed
workers and stores results as zip archives in S3. Each zip contains:
  - content.md  (raw Marker full-PDF output)
  - assets/     (extracted images)
  - info.json   (metadata: hash, filename, tags, marker version)

This module provides the import path: place BlobForge's Marker output into
the pdf-to-wiki artifact store and skip the expensive Marker conversion step
when running `build`. The rest of the pipeline (TOC extraction, section tree
construction, heading splitting, repair, emission, validation) runs normally.

Usage:
  # From a BlobForge conversion zip:
  pdf-to-wiki import-blobforge --pdf /path/to/source.pdf --zip /path/to/hash.zip

  # From an already-extracted content.md:
  pdf-to-wiki import-blobforge --pdf /path/to/source.pdf --markdown /path/to/content.md

  # Then run the build (Marker conversion is skipped, cached output used):
  pdf-to-wiki build SOURCE_ID --engine marker
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from pdf_to_wiki.cache.artifact_store import ArtifactStore
from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.logging import get_logger

logger = get_logger(__name__)


def import_blobforge(
    pdf_path: str,
    config: WikiConfig,
    zip_path: str | None = None,
    markdown_path: str | None = None,
    force: bool = False,
) -> dict:
    """Import a BlobForge conversion into the pdf-to-wiki pipeline.

    Places the BlobForge Marker output into the artifact store as
    `marker_full_md.md`, which causes the pdf-to-wiki Marker engine
    to skip conversion and use the cached output.

    Args:
        pdf_path: Path to the original PDF file (needed for TOC extraction).
        config: Pipeline configuration.
        zip_path: Path to a BlobForge conversion zip (contains content.md).
        markdown_path: Path to an already-extracted content.md file.
        force: Overwrite existing marker_full_md.md if it exists.

    Returns:
        Dict with import status and metadata.
    """
    if not zip_path and not markdown_path:
        raise ValueError("Must provide either --zip or --markdown")

    # Step 1: Read the Marker Markdown content
    if zip_path:
        content_md, info = _read_from_zip(zip_path)
    else:
        content_md = Path(markdown_path).read_text(encoding="utf-8")
        info = {}

    if not content_md.strip():
        raise ValueError("No content found in BlobForge output (empty content.md)")

    logger.info(f"Read BlobForge output: {len(content_md):,} chars")

    # Step 2: Register the PDF (needed for TOC extraction, page labels, etc.)
    from pdf_to_wiki.ingest.register_pdf import register_pdf

    source = register_pdf(pdf_path, config, force=force)
    source_id = source.source_id
    sha256 = source.sha256
    logger.info(f"Registered PDF: {source_id} ({source.page_count} pages)")

    # Step 3: Place the Marker output as the cached artifact
    artifacts = ArtifactStore(config.resolved_artifact_dir())

    marker_artifact_path = artifacts.artifact_path(sha256, "marker_full_md", suffix=".md")
    if marker_artifact_path.exists() and not force:
        existing_size = marker_artifact_path.stat().st_size
        logger.warning(
            f"Marker artifact already exists for {source_id} "
            f"({existing_size:,} bytes). Use --force to overwrite."
        )
        return {
            "source_id": source_id,
            "status": "skipped_existing",
            "chars": existing_size,
            "message": "Marker artifact already exists; use --force to overwrite",
        }

    artifacts.save_text(sha256, "marker_full_md", content_md, suffix=".md")
    logger.info(f"Cached Marker output: {len(content_md):,} chars → {marker_artifact_path}")

    # Step 4: Also extract images from the zip if available
    image_count = 0
    if zip_path:
        image_count = _extract_images_from_zip(zip_path, source_id, config)

    # Step 5: Save the info.json as a blobforge_info artifact (for reference)
    if info:
        artifacts.save_json(sha256, "blobforge_info", info)
        logger.info(f"Saved BlobForge metadata: {list(info.keys())}")

    return {
        "source_id": source_id,
        "status": "imported",
        "chars": len(content_md),
        "images": image_count,
        "message": (
            f"Imported {len(content_md):,} chars from BlobForge. "
            f"Run 'pdf-to-wiki build {source_id} --engine marker' to complete the pipeline."
        ),
    }


def _read_from_zip(zip_path: str) -> tuple[str, dict]:
    """Read content.md and info.json from a BlobForge conversion zip.

    Returns:
        Tuple of (markdown_text, info_dict).
    """
    md_text = ""
    info = {}

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()

        # Read content.md
        if "content.md" in names:
            md_text = zf.read("content.md").decode("utf-8", errors="replace")
        else:
            # Try to find any .md file
            md_files = [n for n in names if n.endswith(".md")]
            if md_files:
                md_text = zf.read(md_files[0]).decode("utf-8", errors="replace")
                logger.warning(f"No content.md found; using {md_files[0]} instead")

        # Read info.json
        if "info.json" in names:
            try:
                info = json.loads(zf.read("info.json").decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.warning("Could not parse info.json from zip")

    return md_text, info


def _extract_images_from_zip(
    zip_path: str,
    source_id: str,
    config: WikiConfig,
) -> int:
    """Extract images from a BlobForge zip into the wiki assets directory.

    BlobForge saves images under `assets/` in the zip. We translate
    them to `books/<source_id>/.assets/` in the wiki output directory.

    Note: pdf-to-wiki normally extracts images via PyMuPDF (which gives
    better deduplication). This extraction is provided as a fallback
    when the original PDF is unavailable or PyMuPDF extraction fails.

    Returns:
        Number of images extracted.
    """
    import shutil

    output_dir = config.resolved_output_dir()
    assets_dir = output_dir / config.books_dir / source_id / ".assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            # Match assets/* entries
            if not name.startswith("assets/"):
                continue
            if name.endswith("/"):
                continue

            # Get just the filename part
            filename = name[len("assets/"):]
            if not filename or filename.startswith("..") or "/" in filename:
                continue

            # Convert image extension to .png for consistency
            # (BlobForge may save as .jpeg or .png)
            target = assets_dir / filename

            with zf.open(name) as src:
                with open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            count += 1

    if count:
        logger.info(f"Extracted {count} images from BlobForge zip to {assets_dir}")

    return count


def import_from_s3(
    pdf_path: str,
    file_hash: str,
    config: WikiConfig,
    force: bool = False,
) -> dict:
    """Import a BlobForge conversion from S3 by downloading the zip.

    This connects to the BlobForge S3 bucket, downloads the completed
    conversion zip, and imports it. Requires BlobForge S3 credentials
    to be configured (environment variables or blobforge config).

    Args:
        pdf_path: Path to the original PDF file.
        file_hash: SHA-256 hash of the PDF (as used by BlobForge).
        config: pdf-to-wiki pipeline configuration.
        force: Overwrite existing artifacts.

    Returns:
        Dict with import status and metadata.
    """
    import tempfile

    try:
        from blobforge.s3_client import S3Client
    except ImportError:
        raise ImportError(
            "BlobForge is not installed. Install it with: "
            "uv add blobforge (or pip install blobforge)"
        )

    client = S3Client()
    done_key = f"store/out/{file_hash}.zip"

    # Check if conversion exists
    if not client.exists(done_key):
        raise FileNotFoundError(
            f"No completed BlobForge conversion found for hash {file_hash[:12]}... "
            f"at {done_key}"
        )

    # Download to temp file and import
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        client.download_file(done_key, tmp_path)
        logger.info(f"Downloaded BlobForge conversion: {tmp_path}")
        return import_blobforge(pdf_path, config, zip_path=tmp_path, force=force)
    finally:
        Path(tmp_path).unlink(missing_ok=True)