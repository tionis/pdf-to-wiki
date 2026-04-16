"""Page-label extraction — extract printed page labels from a PDF using pypdf.

This is a deterministic operation; no LLM is involved.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pypdf import PdfReader

from pdf_to_wiki.cache.artifact_store import ArtifactStore
from pdf_to_wiki.cache.db import CacheDB
from pdf_to_wiki.cache.manifests import StepManifestStore
from pdf_to_wiki.config import WikiConfig
from pdf_to_wiki.logging import get_logger
from pdf_to_wiki.models import PageLabel, ProvenanceRecord

logger = get_logger(__name__)


def extract_page_labels(
    source_id: str,
    config: WikiConfig,
    force: bool = False,
) -> list[PageLabel]:
    """Extract page labels from the PDF.

    Page labels are the "printed" page numbers (e.g. Roman numerals
    for front matter, Arabic numerals for body pages).

    Extraction strategy (in priority order):
    1. pypdf's page_labels property (most reliable)
    2. Manual /PageLabels dict parsing
    3. Roman-numeral front-matter heuristic detection
    4. Simple 1-indexed numeric fallback

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
        cached = artifacts.load_json(source.sha256, "page_labels")
        if cached is not None:
            logger.info(f"Page labels for {source_id} already cached. Use --force to re-extract.")
            labels = [PageLabel(**e) for e in cached]
            db.close()
            return labels

    manifests.mark_running(source_id, "page_labels")

    # Extract page labels
    reader = PdfReader(source.path)
    page_labels = _compute_page_labels(reader, source.page_count, pdf_path=source.path)

    # Persist
    label_data = [pl.model_dump() for pl in page_labels]
    artifacts.save_json(source.sha256, "page_labels", label_data)

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


def _compute_page_labels(
    reader: PdfReader,
    page_count: int,
    pdf_path: str | None = None,
) -> list[PageLabel]:
    """Compute page labels using multiple strategies.

    Priority:
    1. pypdf's built-in page_labels property (most reliable)
    2. Manual /PageLabels dict parsing
    3. Roman-numeral front-matter heuristic (requires pdf_path)
    4. Simple sequential numbering
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

    # Try Roman-numeral front-matter detection heuristic
    if not labels and pdf_path:
        roman_labels = _detect_roman_numerals(pdf_path, page_count)
        if roman_labels:
            labels = roman_labels
            logger.info(
                f"Detected {sum(1 for l in labels if not l.label.isdigit())} "
                f"Roman-numeral front-matter pages"
            )

    # Final fallback: generate default numeric labels (1-indexed)
    if not labels:
        logger.info("No explicit /PageLabels found; falling back to 1-indexed numeric labels")
        labels = [PageLabel(page_index=i, label=str(i + 1)) for i in range(page_count)]

    return labels


# ---- Roman-numeral detection heuristic ----

# Regex that matches common Roman numeral page-label forms:
#   "i", "ii", "iii", "iv", "v", "vi", ... up to "c" (100)
# Also matches with trailing punctuation or surrounding whitespace,
# since PDF pages might have the numeral as a standalone page number.
_ROMAN_NUMERAL_RE = re.compile(
    r"^(?:M{0,3})(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{1,3})$",
    re.IGNORECASE,
)


def _is_roman_numeral(text: str) -> bool:
    """Check if a non-empty string is a Roman numeral (i-xx)."""
    t = text.strip()
    if not t or len(t) > 10:  # Skip very long strings
        return False
    # Reject strings that look like English words (too many vowels, etc.)
    if t.lower() in ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix",
                      "x", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii",
                      "xviii", "xix", "xx"):
        return True
    return bool(_ROMAN_NUMERAL_RE.match(t))


def _roman_to_int(s: str) -> int:
    """Convert a Roman numeral string to an integer."""
    s = s.upper()
    vals = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    total = 0
    for i, ch in enumerate(s):
        if ch not in vals:
            return 0
        if i + 1 < len(s) and vals[s[i + 1]] > vals[ch]:
            total -= vals[ch]
        else:
            total += vals[ch]
    return total


def _detect_roman_numerals(
    pdf_path: str,
    page_count: int,
    max_front_pages: int = 30,
) -> list[PageLabel] | None:
    """Detect Roman-numeral front-matter page labels via text scanning.

    Many rulebook PDFs use Roman numerals (i, ii, iii...) for front
    matter and Arabic numerals (1, 2, 3...) for the body, but don't
    include a /PageLabels dict in the PDF structure.

    This heuristic scans the first max_front_pages pages looking for
    standalone Roman numerals (typically at the bottom of the page as
    printed page numbers). If a consecutive sequence of Roman numerals
    starting from "i" is found, the front-matter pages get Roman labels
    and the body pages get Arabic labels starting from 1.

    Returns None if no convincing Roman-numeral sequence is detected.
    """
    import fitz

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return None

    # Scan first N pages for Roman numeral candidates
    roman_candidates: dict[int, str] = {}  # page_index → roman numeral string

    for page_idx in range(min(page_count, max_front_pages)):
        page = doc[page_idx]
        text = page.get_text("text")
        # Look for standalone Roman numerals on the page.
        # These are typically:
        # - A line with just the numeral and whitespace
        # - The numeral at the bottom of the page (page footer)
        # We check lines from the bottom up to find likely page numbers.
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            continue

        # Check last few lines (page numbers are often at bottom)
        # and any standalone short lines
        candidates = []
        for line in lines[-5:]:
            if _is_roman_numeral(line) and len(line) <= 5:
                candidates.append(line.lower())
        # Also check any standalone short line (all alone on its own)
        for line in lines:
            if _is_roman_numeral(line) and len(line) <= 5:
                if line.lower() not in candidates:
                    candidates.append(line.lower())

        if candidates:
            # Use the shortest one (most likely the page number, not a word)
            # E.g., both "i" and "iii" might appear; prefer "i" for page 0
            roman_candidates[page_idx] = sorted(candidates, key=len)[0]

    doc.close()

    if not roman_candidates:
        return None

    # Validate: check if we found a convincing consecutive sequence.
    # A "convincing" sequence means:
    # - Starts at page 0 (or very close) with "i"
    # - Consecutive pages have consecutive Roman numerals (i, ii, iii...)
    # - At least 2 Roman-numeral pages found
    # - The sequence is not ambiguous (e.g., all pages just "i")

    # Check if the first candidate is on page 0 and equals "i"
    first_idx = min(roman_candidates.keys())
    if roman_candidates[first_idx] != "i" and first_idx > 2:
        # Doesn't start with "i" and isn't near the start — skip
        return None

    # Try to find a consecutive sequence starting from "i"
    sequence: dict[int, str] = {}  # page_index → roman numeral
    expected_val = 1  # Start looking for "i" (value 1)

    for page_idx in range(page_count):
        if page_idx in roman_candidates:
            found_val = _roman_to_int(roman_candidates[page_idx])
            if found_val == expected_val:
                sequence[page_idx] = roman_candidates[page_idx]
                expected_val += 1
            elif found_val > expected_val and expected_val == 1:
                # Gap at the start — e.g., page 0 has "iii"
                # This might mean the first few pages (cover, title) aren't numbered
                # Accept if we find a reasonable start
                if found_val > 0 and found_val <= 5:
                    # Try to find the page where "i" would be
                    # The offset is found_val - 1 (e.g., "iii" on page 2 means offset=2)
                    offset = found_val - 1
                    candidate_page = page_idx - offset
                    if candidate_page >= 0 and candidate_page not in roman_candidates:
                        # Accept the sequence from here, noting pages before
                        # candidate_page have no Roman numbering
                        break
                    sequence[page_idx] = roman_candidates[page_idx]
                    expected_val = found_val + 1
            elif found_val < expected_val:
                # Out of sequence — stop
                break
        elif sequence and not page_idx in roman_candidates:
            # Gap in the sequence — might be end of Roman-numeral section
            # Only accept gaps of 1 (e.g., a blank page)
            if expected_val > 2 and (page_idx + 1) in roman_candidates:
                # Next page continues — it's just a blank page, skip
                continue
            else:
                break

    if len(sequence) < 2:
        return None

    # Build the full label list
    labels: list[PageLabel] = []
    roman_end_page = max(sequence.keys())  # Last page with Roman numeral

    # Pages before the first Roman-numeral page get no label (or "i" offset)
    first_roman_page = min(sequence.keys())

    for page_idx in range(page_count):
        if page_idx in sequence:
            # Roman-numeral page
            labels.append(PageLabel(page_index=page_idx, label=sequence[page_idx]))
        elif page_idx < first_roman_page:
            # Pages before the Roman section — likely cover, title, TOC
            # Assign negative-offset labels so they don't clash with body pages
            offset = first_roman_page - page_idx
            labels.append(PageLabel(page_index=page_idx, label=f"pre-{offset}"))
        elif page_idx > roman_end_page:
            # Body pages — 1-indexed Arabic
            body_page = page_idx - roman_end_page
            labels.append(PageLabel(page_index=page_idx, label=str(body_page)))
        else:
            # Gap within the Roman section — fill in the expected numeral
            # (blank pages between Roman-numeral front matter)
            expected_roman = _to_roman(1 + page_idx - first_roman_page).lower()
            labels.append(PageLabel(page_index=page_idx, label=expected_roman))

    logger.info(
        f"Roman-numeral front-matter detected: {first_roman_page}-{roman_end_page} "
        f"({len(sequence)} Roman-numeral pages, "
        f"{page_count - roman_end_page - 1} body pages)"
    )

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