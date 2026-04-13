"""PDF inspection — display basic PDF metadata for a registered source."""

from __future__ import annotations

from rulebook_wiki.cache.db import CacheDB
from rulebook_wiki.config import WikiConfig
from rulebook_wiki.logging import get_logger
from rulebook_wiki.models import PdfSource

logger = get_logger(__name__)


def inspect_pdf(source_id: str, config: WikiConfig) -> PdfSource | None:
    """Look up an already-registered PDF source and return its metadata."""
    db = CacheDB(config.resolved_cache_db_path())
    source = db.get_pdf_source(source_id)
    db.close()
    if source is None:
        logger.warning(f"No registered PDF with source_id={source_id!r}")
    return source