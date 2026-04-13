"""Pluggable extraction engine architecture.

Provides a base class and registry for PDF text extraction backends.
Each engine takes a PDF path + page range and returns extracted text.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rulebook_wiki.config import WikiConfig

# ── Engine registry ──────────────────────────────────────────────────

_ENGINES: dict[str, type[BaseEngine]] = {}


def register_engine(name: str):
    """Decorator to register an extraction engine by name."""
    def decorator(cls: type[BaseEngine]) -> type[BaseEngine]:
        _ENGINES[name] = cls
        return cls
    return decorator


def get_engine(name: str, config: WikiConfig) -> BaseEngine:
    """Instantiate a registered extraction engine by name."""
    if name not in _ENGINES:
        available = ", ".join(sorted(_ENGINES.keys())) or "(none)"
        raise ValueError(
            f"Unknown extraction engine {name!r}. Available: {available}"
        )
    return _ENGINES[name](config)


def list_engines() -> list[str]:
    """Return sorted list of registered engine names."""
    return sorted(_ENGINES.keys())


# ── Base class ───────────────────────────────────────────────────────

class BaseEngine(ABC):
    """Abstract base class for PDF text extraction engines.

    An engine is responsible for extracting text from a PDF document
    for a given page range. It may use any technique (PyMuPDF, Marker,
    OCR, etc.) but must return plain text for each page range requested.
    """

    def __init__(self, config: WikiConfig) -> None:
        self.config = config

    @abstractmethod
    def extract_page_range(
        self,
        pdf_path: str,
        start_page: int,
        end_page: int,
    ) -> str:
        """Extract text for a page range (0-indexed, inclusive).

        Args:
            pdf_path: Absolute path to the PDF file.
            start_page: First page index (0-based).
            end_page: Last page index (0-based, inclusive).

        Returns:
            Extracted and cleaned text content.
        """
        ...

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Human-readable engine name for provenance tracking."""
        ...

    @property
    @abstractmethod
    def engine_version(self) -> str:
        """Version string for provenance tracking."""
        ...