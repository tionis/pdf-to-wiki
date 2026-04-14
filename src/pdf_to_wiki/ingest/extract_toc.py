"""TOC extraction — extract the embedded PDF bookmarks / outline using PyMuPDF.

This is a deterministic operation; no LLM is involved.
"""

from __future__ import annotations

from datetime import datetime, timezone

import fitz  # PyMuPDF

from pdf_to_wiki.cache.artifact_store import ArtifactStore
from pdf_to_wiki.cache.db import CacheDB
from pdf_to_wiki.cache.manifests import StepManifestStore
from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.logging import get_logger
from pdf_to_wiki.models import PdfSource, ProvenanceRecord, TocEntry

logger = get_logger(__name__)


def extract_toc(
    source_id: str,
    config: WikiConfig,
    force: bool = False,
) -> list[TocEntry]:
    """Extract the PDF's embedded TOC / bookmarks.

    - Reads the TOC via PyMuPDF
    - Normalizes level numbering (PyMuPDF uses 1-based, we keep 1-based)
    - Page numbers are converted from 1-based (PyMuPDF) to 0-based
    - Persists the TOC as a JSON artifact
    - Records provenance

    Returns a list of TocEntry objects.
    """
    db = CacheDB(config.resolved_cache_db_path())
    artifacts = ArtifactStore(config.resolved_artifact_dir())
    manifests = StepManifestStore(db)

    # Look up source
    source = db.get_pdf_source(source_id)
    if source is None:
        raise ValueError(f"No registered PDF with source_id={source_id!r}. Run 'register' first.")

    # Check cache
    if not force and manifests.is_completed(source_id, "toc"):
        cached = artifacts.load_json(source_id, "toc")
        if cached is not None:
            logger.info(f"TOC for {source_id} already cached. Use --force to re-extract.")
            entries = [TocEntry(**e) for e in cached]
            db.close()
            return entries

    manifests.mark_running(source_id, "toc")

    # Extract TOC
    doc = fitz.open(source.path)
    raw_toc = doc.get_toc()  # List of [level, title, page] where page is 1-based
    doc.close()

    entries: list[TocEntry] = []
    for level, title, page_1based in raw_toc:
        page_0based = max(0, page_1based - 1)  # Convert to 0-based; clamp to 0 for negative
        # Normalize title: strip leading/trailing whitespace and collapse internal newlines
        # (PyMuPDF sometimes splits long bookmark titles across lines)
        title_clean = " ".join(title.split())
        entries.append(
            TocEntry(
                level=level,
                title=title_clean,
                pdf_page=page_0based,
            )
        )

    # Persist
    toc_data = [e.model_dump() for e in entries]
    artifacts.save_json(source_id, "toc", toc_data)

    now = datetime.now(timezone.utc).isoformat()
    prov = ProvenanceRecord(
        artifact_id=f"{source_id}/toc",
        source_id=source_id,
        step="toc",
        tool="pymupdf",
        tool_version=fitz.version[0],
        config_hash="",
        created_at=now,
    )
    db.insert_provenance(prov)
    manifests.mark_completed(source_id, "toc", artifact_path=f"{source_id}/toc.json")

    logger.info(f"Extracted {len(entries)} TOC entries for {source_id}")
    db.close()
    return entries