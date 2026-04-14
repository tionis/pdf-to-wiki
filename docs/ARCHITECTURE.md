# Architecture

## Overview

The Rulebook Wiki Pipeline is a **coordinator pipeline**, not a monolithic converter. PDF → wiki is treated as a sequence of stages with persisted intermediate artifacts. Each stage reads from and writes to the canonical artifact store, and every expensive step is cacheable and resumable.

## Pipeline Stages

```
┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Register │ →  │   TOC    │ →  │  Page Labels  │ →  │ Section  │ →  │ Extract  │ →  │   Emit   │ →  │  Future: │
│   PDF    │    │Extract   │    │   Extract     │    │   Tree   │    │   Text   │    │ Skeleton │    │  Repair  │
│          │    │          │    │               │    │          │    │(engine)  │    │  (MD)   │    │          │
└──────────┘    └──────────┘    └──────────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
     │               │                │                   │               │               │
     └───────────────┴────────────────┴───────────────────┴───────────────┴───────────────┘
                            SQLite Cache + JSON Artifacts
```

### Stage Details

1. **Register** — Fingerprint the PDF (SHA-256), extract basic metadata (title, page count), derive `source_id`, persist `PdfSource` in SQLite and as JSON artifact.
2. **TOC Extract** — Extract the PDF's embedded bookmarks/outline via PyMuPDF. Normalize page numbers to 0-based. Persist as JSON artifact.
3. **Page Labels Extract** — Extract printed page labels (Roman numerals, Arabic numbers) via pypdf. Fall back to 1-indexed numeric labels if no `/PageLabels` dict. Persist as JSON artifact.
4. **Section Tree** — Build a canonical tree of `SectionNode` objects from the TOC + page labels. Compute page ranges, parent-child relationships, and section IDs. This is the backbone of the entire system. Persist as JSON artifact.
5. **Extract Text** — Extract text content using a pluggable extraction engine. **Marker** (default): ML-powered, produces clean Markdown with columns/tables/bold-italic. **PyMuPDF** (fallback): deterministic, column-aware with header/footer removal. Full-PDF Marker output is cached as `marker_full_md.md`. Sections without heading matches fall back to PyMuPDF per-page extraction. Persist as JSON artifact.
6. **Emit Notes** — Generate Markdown files from the section tree. Each section with children becomes a directory with `index.md`; leaf sections become individual `.md` files. YAML frontmatter includes full source and page metadata. Persist an emit manifest.
7. **(Future) Repair** — Normalize broken bullets, fix headings, repair references.
8. **(Future) Link / Enrich** — Rewrite cross-references, build global concept pages.

## Extraction Engine Architecture

### BaseEngine ABC (`extract/__init__.py`)

All extraction engines implement:
- `extract_page_range(pdf_path, start_page, end_page) -> str`
- `engine_name -> str` (for provenance)
- `engine_version -> str` (for provenance)

Engines are registered via `@register_engine("name")` decorator and instantiated via `get_engine("name", config)`.

### Marker Engine (`extract/marker_engine.py`)

- Uses `marker-pdf` library with layout recognition, OCR error detection, table recognition
- Models downloaded on first use (~2GB), cached in `~/.cache/datalab/models/`
- `extract_full_pdf()`: Converts entire PDF in one pass (most efficient)
- `extract_page_range()`: Creates temp PDF excerpt, converts just those pages
- `split_markdown_by_headings()`: Splits full-PDF Markdown into per-section content by matching section titles to heading anchors
- Performance: ~30s/page on CPU (one-time cost, result cached)

### PyMuPDF Engine (`extract/pymupdf_engine.py`)

- Uses PyMuPDF dict-mode extraction with column-aware layout handling
- `repair/clean_text.py`: Header/footer detection, soft-hyphen removal, hard-hyphen rejoin, paragraph assembly, page number stripping
- Performance: ~0.1s/page (no ML models)
- Quality: decent but may have column mixing issues on 2-column layouts

### Engine Selection

- Config: `extract.engine = "marker"` (default) or `"pymupdf"`
- CLI: `--engine marker` or `--engine pymupdf`
- Unknown engines fall back to pymupdf with a warning

### Marker Full-PDF Caching Strategy

1. Convert entire PDF in one Marker call → `marker_full_md.md` artifact
2. Split Markdown by heading anchors → per-section content
3. Sections without heading matches → PyMuPDF fallback
4. On re-run, cached `marker_full_md.md` is reused (no re-conversion)

## Data Model

### Core Models (in `models.py`)

| Model | Purpose |
|-------|---------|
| `PdfSource` | Registered PDF: source_id, path, SHA-256, title, page count |
| `TocEntry` | Single TOC bookmark: level, title, pdf_page (0-based) |
| `PageLabel` | Page index → printed label mapping |
| `SectionNode` | Node in the canonical section tree: section_id, title, slug, level, parent, children, page ranges, printed labels |
| `SectionTree` | Full tree for one PDF: source_id, nodes dict, root_ids list |
| `ProvenanceRecord` | Artifact provenance: who made it, when, with what tool |
| `StepManifest` | Per-step completion tracking in the pipeline |

### Key Invariants

- **Section IDs are globally unique and namespaced**: `source_id/ancestor-slug/child-slug`
- **Page numbers are 0-based** throughout the internal representation
- **Printed page labels are strings** (may be "iii", "117", "A-5")
- **The section tree JSON is the canonical structural representation**, not the Markdown files
- **Markdown is a rendered view** of the section tree

## Caching and Provenance

### SQLite Cache (`cache.db`)

Three tables:
- `pdf_sources` — registered PDF metadata (PK: source_id)
- `step_manifests` — per-step status tracking (PK: source_id + step)
- `provenance` — artifact provenance records (PK: artifact_id)

### Filesystem Artifacts

Files stored under `data/artifacts/<source_id>/`:
- `pdf_source.json` — PdfSource model dump
- `toc.json` — list of TocEntry dumps
- `page_labels.json` — list of PageLabel dumps
- `section_tree.json` — full SectionTree dump
- `marker_full_md.md` — Marker's full-PDF Markdown output (cached)
- `extract_text.json` — section_id → extracted text mapping
- `emit_manifest.json` — section_id → output path mapping

### Cache Semantics

- Each pipeline step checks `StepManifestStore.is_completed()` before running
- If a step's artifact exists and the step is marked completed, it's skipped
- `--force` forces re-run of the current command's step
- `--engine` selects the extraction engine (Marker is default)

## Module Layout

```
src/pdf_to_wiki/
├── __init__.py          # Package version
├── cli.py               # Click CLI commands
├── config.py            # TOML config loading
├── models.py            # Pydantic data models
├── logging.py           # Structured logging
├── ingest/
│   ├── register_pdf.py  # PDF registration and fingerprinting
│   ├── fingerprint.py   # SHA-256 and source_id derivation
│   ├── inspect_pdf.py   # PDF metadata lookup
│   ├── extract_toc.py   # TOC extraction via PyMuPDF
│   ├── extract_page_labels.py  # Page labels via pypdf
│   ├── extract_text.py  # Text extraction (engine dispatch, caching)
│   └── build_section_tree.py   # Canonical section tree construction
├── extract/
│   ├── __init__.py      # BaseEngine ABC, engine registry
│   ├── pymupdf_engine.py # PyMuPDF extraction engine
│   └── marker_engine.py  # Marker extraction engine
├── repair/
│   └── clean_text.py   # Structured extraction + text cleaning
├── emit/
│   ├── markdown_writer.py  # Markdown skeleton emission
│   └── obsidian_paths.py   # Deterministic path generation
├── llm/                 # (Stub) Future: Ollama-backed enrichment
├── cache/
│   ├── db.py            # SQLite cache database
│   ├── artifact_store.py # Filesystem artifact storage
│   └── manifests.py     # Step manifest tracking
└── index/               # (Stub) Future: global catalog and link graph
```

## Design Decisions

1. **TOC is the source of truth for hierarchy.** PDF layout inference can be wrong; embedded bookmarks are more reliable for chapter structure.
2. **Deterministic operations use no LLM.** TOC extraction, page counting, slug generation, page-label extraction, and Markdown emission are deterministic.
3. **LLM usage is constrained and cached.** When LLM steps are added, they must check the cache before calling the model.
4. **Structured intermediates over text-to-text.** The pipeline produces JSON artifacts, not just "PDF in → Markdown out." This enables inspection, debugging, and partial re-runs.
5. **Extraction engines are pluggable.** Marker is the default for quality; PyMuPDF is the fast deterministic fallback. New engines (Docling, OCR) can be added via `@register_engine`.
6. **Marker output is cached at the full-PDF level.** A single Marker call converts the entire PDF; the result is cached as `marker_full_md.md` and split into sections on subsequent runs.
7. **Multi-PDF from the start.** All identities are namespaced by source_id.
8. **Two-layer wiki model (future).** Layer 1: per-source trees preserving the original book structure. Layer 2: global semantic overlay with shared concepts and cross-links.