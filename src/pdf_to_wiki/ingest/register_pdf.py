"""PDF registration — add a PDF source to the pipeline's cache and provenance system."""

from __future__ import annotations

from datetime import datetime, timezone

import fitz  # PyMuPDF

from pdf_to_wiki.cache.artifact_store import ArtifactStore
from pdf_to_wiki.cache.db import CacheDB
from pdf_to_wiki.cache.manifests import StepManifestStore
from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.ingest.fingerprint import compute_sha256, derive_source_id
from pdf_to_wiki.logging import get_logger
from pdf_to_wiki.models import PdfSource, ProvenanceRecord

logger = get_logger(__name__)


def register_pdf(
    pdf_path: str,
    config: WikiConfig,
    force: bool = False,
) -> PdfSource:
    """Register a PDF in the pipeline.

    - Computes SHA-256 fingerprint
    - Derives source_id from filename
    - Extracts basic metadata (title, page count)
    - Persists PdfSource in cache DB
    - Records provenance

    Returns the PdfSource model.
    """
    db = CacheDB(config.resolved_cache_db_path())
    artifacts = ArtifactStore(config.resolved_artifact_dir())
    manifests = StepManifestStore(db)

    source_id = derive_source_id(pdf_path)
    sha256 = compute_sha256(pdf_path)

    # Check cache
    existing = db.get_pdf_source(source_id)
    if existing and existing.sha256 == sha256 and not force:
        logger.info(f"PDF {source_id} already registered (sha256={sha256[:12]}…). Use --force to reregister.")
        return existing

    # Extract metadata
    doc = fitz.open(pdf_path)
    title = doc.metadata.get("title") or None
    page_count = doc.page_count
    doc.close()

    source = PdfSource(
        source_id=source_id,
        path=str(pdf_path),
        sha256=sha256,
        title=title,
        page_count=page_count,
    )

    # Persist
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_pdf_source(source, registered_at=now)

    # Save source metadata as artifact
    artifacts.save_json(source_id, "pdf_source", source.model_dump())

    # Record provenance
    prov = ProvenanceRecord(
        artifact_id=f"{source_id}/pdf_source",
        source_id=source_id,
        step="register",
        tool="pymupdf",
        tool_version=fitz.version[0],
        config_hash="",
        created_at=now,
    )
    db.insert_provenance(prov)

    # Mark step
    manifests.mark_completed(source_id, "register", artifact_path=f"{source_id}/pdf_source.json")

    logger.info(
        f"Registered {source_id}: {page_count} pages, sha256={sha256[:12]}…"
    )

    db.close()
    return source