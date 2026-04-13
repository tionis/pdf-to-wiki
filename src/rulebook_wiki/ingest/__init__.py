"""PDF ingestion: registration, fingerprinting, inspection, TOC, page-label, and text extraction."""

from .register_pdf import register_pdf
from .fingerprint import compute_sha256, derive_source_id
from .extract_toc import extract_toc
from .extract_page_labels import extract_page_labels
from .extract_text import extract_text
from .build_section_tree import build_section_tree

__all__ = [
    "register_pdf",
    "compute_sha256",
    "derive_source_id",
    "extract_toc",
    "extract_page_labels",
    "extract_text",
    "build_section_tree",
]