"""Text extraction from PDF using PyMuPDF.

This is a deterministic extraction engine. It extracts text page-by-page
for the page ranges defined in the section tree, producing structured
artifacts that can be merged into the Markdown output.

PyMuPDF's get_text() is the baseline extractor. Marker or other engines
can be substituted later via the extract/ subpackage.
"""

from __future__ import annotations

from datetime import datetime, timezone

import fitz  # PyMuPDF

from rulebook_wiki.cache.artifact_store import ArtifactStore
from rulebook_wiki.cache.db import CacheDB
from rulebook_wiki.cache.manifests import StepManifestStore
from rulebook_wiki.config import WikiConfig
from rulebook_wiki.logging import get_logger
from rulebook_wiki.models import ProvenanceRecord, SectionNode, SectionTree

logger = get_logger(__name__)


def extract_text(
    source_id: str,
    config: WikiConfig,
    force: bool = False,
) -> dict[str, str]:
    """Extract text from the PDF for each section's page range.

    Uses PyMuPDF's page.get_text() to extract text content for the
    page ranges defined in the section tree. Results are persisted
    as JSON artifacts.

    Returns a dict mapping section_id → extracted text content.
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

    manifests.mark_running(source_id, "extract_text")

    # Load section tree
    tree_data = artifacts.load_json(source_id, "section_tree")
    if tree_data is None:
        raise ValueError(f"No section tree for {source_id}. Run 'build-section-tree' first.")
    tree = SectionTree(**tree_data)

    # Extract text per section
    doc = fitz.open(source.path)
    extracted: dict[str, str] = {}

    for section_id, node in tree.nodes.items():
        text = _extract_section_text(doc, node)
        extracted[section_id] = text

    doc.close()

    # Persist
    artifacts.save_json(source_id, "extract_text", extracted)

    now = datetime.now(timezone.utc).isoformat()
    prov = ProvenanceRecord(
        artifact_id=f"{source_id}/extract_text",
        source_id=source_id,
        step="extract_text",
        tool="pymupdf",
        tool_version=fitz.version[0],
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


def _extract_section_text(doc: fitz.Document, node: SectionNode) -> str:
    """Extract text content for a single section from the PDF.

    Extracts text from all pages in the section's page range,
    joining them with blank line separators. Attempts to
    preserve paragraph breaks while removing excessive whitespace.
    """
    parts: list[str] = []

    for page_idx in range(node.pdf_page_start, node.pdf_page_end + 1):
        if page_idx >= doc.page_count:
            break
        page = doc[page_idx]
        text = page.get_text("text")
        if text.strip():
            parts.append(text.strip())

    if not parts:
        return ""

    # Join pages with double newline, then normalize internal whitespace
    raw = "\n\n".join(parts)

    # Clean up common extraction artifacts:
    # - Collapse runs of 3+ blank lines into 2
    # - Strip trailing whitespace from lines
    lines = raw.split("\n")
    cleaned_lines: list[str] = []
    prev_blank = False

    for line in lines:
        stripped = line.rstrip()
        is_blank = stripped == ""

        # Skip consecutive blank lines beyond 1 (preserve paragraph breaks)
        if is_blank and prev_blank:
            continue

        cleaned_lines.append(stripped)
        prev_blank = is_blank

    result = "\n".join(cleaned_lines).strip()
    return result