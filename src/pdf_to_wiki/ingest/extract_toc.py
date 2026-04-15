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

    # If no embedded TOC, synthesize one from font-size headings
    if not raw_toc:
        logger.info(f"No embedded TOC found in {source.path}. Synthesizing from font-size headings...")
        raw_toc = _synthesize_toc_from_headings(doc, source.page_count)

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


def _synthesize_toc_from_headings(
    doc: fitz.Document,
    page_count: int,
    min_pages_per_section: int = 1,
) -> list[list[int, str, int]]:
    """Synthesize a TOC from font-size heading detection when the PDF has no bookmarks.

    Scans each page looking for text spans with font sizes significantly
    larger than the body text. Lines with font size >= 1.3× the body text
    are treated as headings.

    Heading levels are estimated by relative font size:
    - >= 2.0× body text → level 1 (chapter)
    - >= 1.5× body text → level 2 (section)
    - >= 1.3× body text → level 3 (subsection)

    Returns:
        List of [level, title, page_1based] entries compatible with
        PyMuPDF's get_toc() format.
    """
    from collections import Counter

    # First pass: determine body text font size
    font_sizes = []
    for page_num in range(min(page_count, 50)):
        page = doc[page_num]
        data = page.get_text("dict")
        for block in data.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if span["text"].strip() and not span["text"].strip().isdigit():
                        font_sizes.append(span["size"])

    if not font_sizes:
        logger.warning("No text found in PDF; cannot synthesize TOC")
        return []

    body_size = Counter(font_sizes).most_common(1)[0][0]
    logger.info(f"Body text font size: {body_size:.1f}")

    # Second pass: detect headings
    headings: list[tuple[int, str, int]] = []  # (level, title, page_0based)

    for page_num in range(page_count):
        page = doc[page_num]
        data = page.get_text("dict")

        for block in data.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                line_text = ""
                max_size = 0
                for span in line["spans"]:
                    text = span["text"].strip()
                    if text:
                        line_text += (" " if line_text else "") + text
                        max_size = max(max_size, span["size"])

                if not line_text or max_size < body_size * 1.3:
                    continue

                # Skip lines that are just page numbers
                if line_text.strip().isdigit():
                    continue

                # Skip very short headings (likely running headers)
                if len(line_text.strip()) < 3:
                    continue

                # Determine heading level based on relative font size
                if max_size >= body_size * 2.0:
                    level = 1
                elif max_size >= body_size * 1.5:
                    level = 2
                else:
                    level = 3

                headings.append((level, line_text.strip(), page_num))

    if not headings:
        logger.warning("No headings detected in PDF; creating single-section TOC")
        return [[1, "Document", 1]]

    # Deduplicate consecutive same-page same-level headings
    # (running headers on consecutive pages)
    deduped = []
    prev = None
    for level, title, page in headings:
        key = (level, title)
        if key == prev:
            continue  # Skip duplicate
        prev = key
        deduped.append([level, title, page + 1])  # Convert to 1-based page

    # If we only got level 3 headings, promote them
    levels = set(h[0] for h in deduped)
    if levels == {3}:
        deduped = [[1, t, p] for _, t, p in deduped]
    elif levels == {2, 3} or levels == {3, 2}:
        deduped = [
            [1 if l == 2 else 2, t, p]
            for l, t, p in deduped
        ]

    logger.info(f"Synthesized {len(deduped)} TOC entries from font-size headings")
    return deduped