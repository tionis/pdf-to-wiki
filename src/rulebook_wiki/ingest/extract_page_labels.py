"""Page-label extraction — extract printed page labels from a PDF using pypdf.

This is a deterministic operation; no LLM is involved.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pypdf import PdfReader

from rulebook_wiki.cache.artifact_store import ArtifactStore
from rulebook_wiki.cache.db import CacheDB
from rulebook_wiki.cache.manifests import StepManifestStore
from rulebook_wiki.config import WikiConfig
from rulebook_wiki.logging import get_logger
from rulebook_wiki.models import PageLabel, ProvenanceRecord

logger = get_logger(__name__)


def extract_page_labels(
    source_id: str,
    config: WikiConfig,
    force: bool = False,
) -> list[PageLabel]:
    """Extract page labels from the PDF.

    Page labels are the "printed" page numbers (e.g. Roman numerals
    for front matter, Arabic numerals for body pages).

    If the PDF has no explicit page labels, returns an empty list.
    Uses pypdf because it provides access to the /PageLabels PDF structure.

    Returns a list of PageLabel objects mapping 0-based page indices
    to printed label strings.
    """
    db = CacheDB(config.resolved_cache_db_path())
    artifacts = ArtifactStore(config.resolved_artifact_dir())
    manifests = StepManifestStore(db)

    source = db.get_pdf_source(source_id)
    if source is None:
        raise ValueError(f"No registered PDF with source_id={source_id!r}. Run 'register' first.")

    # Check cache
    if not force and manifests.is_completed(source_id, "page_labels"):
        cached = artifacts.load_json(source_id, "page_labels")
        if cached is not None:
            logger.info(f"Page labels for {source_id} already cached. Use --force to re-extract.")
            labels = [PageLabel(**e) for e in cached]
            db.close()
            return labels

    manifests.mark_running(source_id, "page_labels")

    # Extract page labels
    reader = PdfReader(source.path)
    page_labels = _compute_page_labels(reader, source.page_count)

    # Persist
    label_data = [pl.model_dump() for pl in page_labels]
    artifacts.save_json(source_id, "page_labels", label_data)

    now = datetime.now(timezone.utc).isoformat()
    prov = ProvenanceRecord(
        artifact_id=f"{source_id}/page_labels",
        source_id=source_id,
        step="page_labels",
        tool="pypdf",
        tool_version=getattr(reader, "_version", "unknown"),
        config_hash="",
        created_at=now,
    )
    db.insert_provenance(prov)
    manifests.mark_completed(source_id, "page_labels", artifact_path=f"{source_id}/page_labels.json")

    logger.info(f"Extracted {len(page_labels)} page labels for {source_id}")
    db.close()
    return page_labels


def _compute_page_labels(reader: PdfReader, page_count: int) -> list[PageLabel]:
    """Compute page labels using pypdf's built-in page_labels property.

    pypdf >= 3.0 exposes a `page_labels` property that handles all the
    /PageLabels parsing internally, including Roman numerals, prefixes,
    and style codes. We prefer this over manual parsing.

    Falls back to manual /PageLabels parsing if the property is not
    available, and to simple sequential numbering if nothing works.
    """
    labels: list[PageLabel] = []

    # Try pypdf's built-in page_labels property first (most reliable)
    try:
        page_label_list = reader.page_labels
        if page_label_list and len(page_label_list) == page_count:
            labels = [
                PageLabel(page_index=i, label=str(label))
                for i, label in enumerate(page_label_list)
            ]
            logger.info(f"Extracted {len(labels)} page labels from pypdf page_labels property")
            return labels
        elif page_label_list:
            # Partial page labels — use what we have and fill in the rest
            for i in range(page_count):
                if i < len(page_label_list):
                    labels.append(PageLabel(page_index=i, label=str(page_label_list[i])))
                else:
                    labels.append(PageLabel(page_index=i, label=str(i + 1)))
            logger.info(f"Extracted partial page labels from pypdf ({len(page_label_list)} of {page_count})")
            return labels
    except Exception as e:
        logger.debug(f"pypdf page_labels property not available: {e}")

    # Try manual /PageLabels parsing as fallback
    try:
        root_obj = reader.trailer.get("/Root")
        if root_obj is not None:
            # Resolve indirect reference if needed
            if hasattr(root_obj, "get_object"):
                root_dict = root_obj.get_object()
            else:
                root_dict = root_obj

            if isinstance(root_dict, dict) and "/PageLabels" in root_dict:
                page_label_info = root_dict["/PageLabels"]
                if hasattr(page_label_info, "get_object"):
                    page_label_info = page_label_info.get_object()
                labels = _parse_page_labels_dict(page_label_info, page_count)
    except Exception as e:
        logger.warning(f"Could not parse /PageLabels from PDF: {e}")

    # Final fallback: generate default numeric labels (1-indexed)
    if not labels:
        logger.info("No explicit /PageLabels found; falling back to 1-indexed numeric labels")
        labels = [PageLabel(page_index=i, label=str(i + 1)) for i in range(page_count)]

    return labels


def _parse_page_labels_dict(label_dict: dict, page_count: int) -> list[PageLabel]:
    """Parse a /PageLabels dictionary into PageLabel objects.

    The /PageLabels dict contains /Nums, an array of (start_page, label_spec)
    pairs. Each label_spec may define a /Prefix, /St (start number), and /S (style).
    """
    labels: list[PageLabel] = []

    nums = label_dict.get("/Nums", [])
    if not nums:
        return labels

    # Build ranges: each pair in /Nums is (page_index, label_spec)
    ranges: list[tuple[int, dict]] = []
    i = 0
    while i < len(nums):
        start = int(nums[i])
        spec = nums[i + 1] if i + 1 < len(nums) else {}
        if isinstance(spec, dict):
            ranges.append((start, spec))
        i += 2

    for idx, (start_page, spec) in enumerate(ranges):
        prefix = str(spec.get("/Prefix", ""))
        style = str(spec.get("/S", ""))
        start_num = int(spec.get("/St", 1))

        # Determine end page
        if idx + 1 < len(ranges):
            end_page = ranges[idx + 1][0]
        else:
            end_page = page_count

        for p in range(start_page, min(end_page, page_count)):
            num = start_num + (p - start_page)
            label_str = _format_label(prefix, style, num)
            labels.append(PageLabel(page_index=p, label=label_str))

    return labels


def _format_label(prefix: str, style: str, num: int) -> str:
    """Format a page label given prefix, style code, and number."""
    style_str = str(style)

    if style_str == "/D":  # Decimal Arabic
        body = str(num)
    elif style_str == "/R":  # Uppercase Roman
        body = _to_roman(num).upper()
    elif style_str == "/r":  # Lowercase Roman
        body = _to_roman(num).lower()
    elif style_str == "/A":  # Uppercase letters
        body = _to_alpha(num).upper()
    elif style_str == "/a":  # Lowercase letters
        body = _to_alpha(num).lower()
    else:
        body = str(num)

    return prefix + body


def _to_roman(num: int) -> str:
    """Convert an integer to a Roman numeral string."""
    val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
    sym = ["M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
    result = []
    for v, s in zip(val, sym):
        while num >= v:
            result.append(s)
            num -= v
    return "".join(result)


def _to_alpha(num: int) -> str:
    """Convert a number to alphabetic labeling (1=a, 2=b, ..., 26=z, 27=aa, ...)."""
    result = []
    n = num
    while n > 0:
        n -= 1
        result.append(chr(ord("a") + (n % 26)))
        n //= 26
    return "".join(reversed(result))