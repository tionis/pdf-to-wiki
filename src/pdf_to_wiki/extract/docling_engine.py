"""Docling extraction engine for PDF-to-Wiki.

Docling is IBM's document conversion library — an alternative to Marker
that's typically faster on CPU and uses a different ML pipeline (layout
model + OCR + table structure). It produces Markdown output with pipe tables
and bold/italic preservation.

Requires the `[docling]` optional dependency group:
    pip install pdf-to-wiki[docling]

Performance: ~1-5s/page on CPU (vs. ~30s/page for Marker). Significantly
faster, with different tradeoffs in table quality and heading detection.

Key differences from Marker:
- Uses DoclingDocument as intermediate (structured JSON), then exports to MD
- Layout model is different (Heron vs. Marker's layout model)
- Table structure model is different
- No page-anchor spans in output (unlike Marker's <span id="page-N-M">)
- Bold/italic preserved in Markdown output
- Supports page_range natively (page_range parameter in convert())

Limitations:
- No heading-based splitting; full-PDF conversion only
- Output may have different heading levels than Marker
- Table quality varies by PDF complexity
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pdf_to_wiki.extract import BaseEngine, register_engine
from pdf_to_wiki.logging import get_logger

if TYPE_CHECKING:
    from pdf_to_wiki.config import WikiConfig

logger = get_logger(__name__)

# Singleton converter — reusing across calls avoids re-loading models
_converter = None
_converter_time = 0.0


def _get_docling_version() -> str:
    """Get Docling version, or 'unavailable' if not installed."""
    try:
        import docling
        return getattr(docling, "__version__", "unknown")
    except ImportError:
        return "unavailable"


@register_engine("docling")
class DoclingEngine(BaseEngine):
    """Extraction engine using IBM Docling for document conversion.

    Docling provides high-quality PDF-to-Markdown conversion with:
    - ML-powered layout analysis (Heron model)
    - Table structure extraction
    - Bold/italic text preservation
    - Significantly faster than Marker on CPU (~1-5s/page vs ~30s/page)

    Requires `pip install pdf-to-wiki[docling]`.
    """

    def __init__(self, config: "WikiConfig") -> None:
        super().__init__(config)
        self._ensure_docling()

    def _ensure_docling(self) -> None:
        """Check that Docling is importable, raise with helpful message if not."""
        try:
            import docling  # noqa: F401
        except ImportError:
            raise ImportError(
                "Docling engine requires the `docling` package. "
                "Install with: pip install pdf-to-wiki[docling] "
                "or: pip install docling"
            )

    @property
    def engine_name(self) -> str:
        return "docling"

    @property
    def engine_version(self) -> str:
        return _get_docling_version()

    def extract_page_range(
        self,
        pdf_path: str,
        start_page: int,
        end_page: int,
        start_heading: str | None = None,
    ) -> str:
        """Extract text for a page range using Docling.

        Docling's convert() supports a page_range parameter (1-based).
        We convert the range and return Markdown output.

        Note: start_heading is ignored — Docling doesn't support
        heading-based mid-page splitting.
        """
        return self._convert_with_docling(pdf_path, start_page, end_page)

    def _convert_with_docling(
        self,
        pdf_path: str,
        start_page: int,
        end_page: int,
    ) -> str:
        """Convert a PDF page range using Docling DocumentConverter.

        Args:
            pdf_path: Path to the PDF file.
            start_page: First page (0-based).
            end_page: Last page (0-based, inclusive).

        Returns:
            Markdown text from Docling conversion.
        """
        global _converter, _converter_time

        from docling.document_converter import DocumentConverter

        # Reuse converter singleton to avoid re-loading models
        if _converter is None:
            logger.info("Initializing Docling converter (first run downloads models)...")
            t0 = time.time()
            _converter = DocumentConverter()
            _converter_time = time.time() - t0
            logger.info(f"Docling converter initialized in {_converter_time:.1f}s")

        # Docling uses 1-based page ranges
        docling_start = start_page + 1
        docling_end = end_page + 1

        try:
            result = _converter.convert(
                pdf_path,
                page_range=(docling_start, docling_end),
            )

            if result.status.value not in ("success", "partial_success"):
                errors = [e.error_message for e in result.errors] if result.errors else []
                error_str = "; ".join(errors) if errors else "unknown error"
                logger.warning(f"Docling conversion issue: {result.status.value}: {error_str}")

            md_text = result.document.export_to_markdown()
            return md_text

        except Exception as e:
            logger.error(f"Docling conversion failed: {e}")
            raise

    def extract_full_pdf(self, pdf_path: str) -> str:
        """Convert an entire PDF to Markdown using Docling.

        This is the equivalent of Marker's full-PDF conversion.
        Returns the complete Markdown output for the document.
        """
        global _converter, _converter_time

        from docling.document_converter import DocumentConverter

        if _converter is None:
            logger.info("Initializing Docling converter...")
            t0 = time.time()
            _converter = DocumentConverter()
            _converter_time = time.time() - t0
            logger.info(f"Docling converter initialized in {_converter_time:.1f}s")

        try:
            result = _converter.convert(pdf_path)

            if result.status.value not in ("success", "partial_success"):
                errors = [e.error_message for e in result.errors] if result.errors else []
                error_str = "; ".join(errors) if errors else "unknown error"
                logger.warning(f"Docling conversion issue: {result.status.value}: {error_str}")

            md_text = result.document.export_to_markdown()
            return md_text

        except Exception as e:
            logger.error(f"Docling full-PDF conversion failed: {e}")
            raise