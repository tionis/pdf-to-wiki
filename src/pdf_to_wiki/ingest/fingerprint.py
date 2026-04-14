"""PDF fingerprinting — SHA-256 hash computation and source_id derivation."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def compute_sha256(pdf_path: str | Path) -> str:
    """Compute SHA-256 of a file's contents.

    Reads in 1 MB chunks to handle large PDFs without excessive memory.
    """
    path = Path(pdf_path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)  # 1 MiB
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def derive_source_id(pdf_path: str | Path) -> str:
    """Derive a stable source_id from the PDF filename.

    Uses the filename stem (without extension), lowercased, with
    spaces, underscores, and parentheses replaced by hyphens.

    This is deterministic and does not depend on file contents,
    making it predictable for CLI usage.  For collision avoidance
    in multi-PDF scenarios, the registration step should check
    for duplicates.
    """
    path = Path(pdf_path)
    stem = path.stem
    # Remove parentheses and brackets
    stem = re.sub(r"[()\[\]{}]", "", stem)
    slug = stem.lower().replace(" ", "-").replace("_", "-")
    # Collapse multiple hyphens
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug or "unnamed-source"