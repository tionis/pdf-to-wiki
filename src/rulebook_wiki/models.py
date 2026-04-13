"""Canonical data models for the rulebook-wiki pipeline.

These models are the source of truth for the in-memory representation.
Markdown is only one rendered view; the JSON-serialized forms of these
models are the canonical persisted artifacts.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PdfSource(BaseModel):
    """Represents a registered PDF source file."""

    source_id: str = Field(description="Stable identifier derived from filename stem")
    path: str = Field(description="Original filesystem path at registration time")
    sha256: str = Field(description="SHA-256 fingerprint of the file contents")
    title: str | None = Field(default=None, description="PDF metadata title")
    page_count: int = Field(description="Number of pages in the PDF")


class TocEntry(BaseModel):
    """A single entry from the PDF's embedded table of contents / bookmarks."""

    level: int = Field(ge=1, description="Bookmark nesting level (1 = top-level chapter)")
    title: str = Field(description="Bookmark title text")
    pdf_page: int = Field(ge=0, description="Target page index (0-based)")


class PageLabel(BaseModel):
    """Mapping from a 0-based page index to a printed page label string."""

    page_index: int = Field(ge=0, description="0-based page index in the PDF")
    label: str = Field(description="Printed page label (e.g. 'iii', '117')")


class SectionNode(BaseModel):
    """A node in the canonical section tree derived from the TOC.

    This is the backbone data structure. Every downstream stage
    (Markdown emission, extraction, repair, linking) references
    section identities from this tree.
    """

    section_id: str = Field(description="Globally unique, namespace-prefixed section identifier")
    source_id: str = Field(description="Owning PDF source_id")
    title: str = Field(description="Section heading text")
    slug: str = Field(description="URL/filename-friendly slug")
    level: int = Field(ge=1, description="Depth in the section tree (1 = chapter)")
    parent_id: str | None = Field(default=None, description="Parent section_id; None for root")
    children: list[str] = Field(default_factory=list, description="Child section_ids in order")
    pdf_page_start: int = Field(ge=0, description="First page (0-based) in this section")
    pdf_page_end: int = Field(ge=0, description="Last page (0-based) inclusive in this section")
    printed_page_start: str | None = Field(default=None, description="Printed label of first page")
    printed_page_end: str | None = Field(default=None, description="Printed label of last page")
    extractor_artifact_path: str | None = Field(
        default=None, description="Path to cached extraction artifact (future)"
    )
    markdown_output_path: str | None = Field(
        default=None, description="Relative path of emitted Markdown file"
    )


class SectionTree(BaseModel):
    """The full section tree for a single PDF source.

    Serialized to JSON as a canonical intermediate artifact.
    """

    source_id: str = Field(description="Owning PDF source_id")
    nodes: dict[str, SectionNode] = Field(
        default_factory=dict, description="section_id → SectionNode, in tree order"
    )
    root_ids: list[str] = Field(
        default_factory=list, description="Top-level section_ids in document order"
    )


class ProvenanceRecord(BaseModel):
    """Provenance metadata for a pipeline artifact."""

    artifact_id: str = Field(description="Unique identifier for the artifact")
    source_id: str = Field(description="Owning PDF source_id")
    section_id: str | None = Field(default=None, description="Related section, if any")
    step: str = Field(description="Pipeline step name")
    tool: str = Field(description="Tool or library name")
    tool_version: str | None = Field(default=None, description="Tool version string")
    config_hash: str = Field(default="", description="Hash of relevant configuration")
    created_at: str = Field(description="ISO 8601 timestamp")


class StepManifest(BaseModel):
    """Record of a completed pipeline step for a source."""

    source_id: str
    step: str
    status: str = Field(description="pending | running | completed | failed | skipped")
    artifact_path: str | None = Field(default=None, description="Relative path under artifact_dir")
    started_at: str | None = None
    completed_at: str | None = None
    config_hash: str = ""