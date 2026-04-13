# Architecture

## Overview

The Rulebook Wiki Pipeline is a **coordinator pipeline**, not a monolithic converter. PDF → wiki is treated as a sequence of stages with persisted intermediate artifacts. Each stage reads from and writes to the canonical artifact store, and every expensive step is cacheable and resumable.

## Pipeline Stages

```
┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Register │ →  │   TOC    │ →  │  Page Labels  │ →  │ Section  │ →  │   Emit   │ →  │  Future: │
│   PDF    │    │Extract   │    │   Extract     │    │   Tree   │    │ Skeleton │    │ Extract  │
│          │    │          │    │               │    │          │    │  (MD)   │    │ + Repair │
└──────────┘    └──────────┘    └──────────────┘    └──────────┘    └──────────┘    └──────────┘
     │               │                │                   │               │
     └───────────────┴────────────────┴───────────────────┴───────────────┘
                            SQLite Cache + JSON Artifacts
```

### Stage Details

1. **Register** — Fingerprint the PDF (SHA-256), extract basic metadata (title, page count), derive `source_id`, persist `PdfSource` in SQLite and as JSON artifact.
2. **TOC Extract** — Extract the PDF's embedded bookmarks/outline via PyMuPDF. Normalize page numbers to 0-based. Persist as JSON artifact.
3. **Page Labels Extract** — Extract printed page labels (Roman numerals, Arabic numbers) via pypdf. Fall back to 1-indexed numeric labels if no `/PageLabels` dict. Persist as JSON artifact.
4. **Section Tree** — Build a canonical tree of `SectionNode` objects from the TOC + page labels. Compute page ranges, parent-child relationships, and section IDs. This is the backbone of the entire system. Persist as JSON artifact.
5. **Emit Skeleton** — Generate Markdown files from the section tree. Each section with children becomes a directory with `index.md`; leaf sections become individual `.md` files. YAML frontmatter includes full source and page metadata. Persist an emit manifest.
6. **(Future) Extract** — Run PDF text extraction (Marker or alternative) on section page ranges. Store structured intermediate artifacts.
7. **(Future) Repair** — Normalize broken bullets, fix headings, repair references. LLM-assisted when deterministic logic is insufficient.
8. **(Future) Link / Enrich** — Rewrite cross-references, build global concept pages, create entity registries.

## Data Model

### Core Models (in `models.py`)

| Model | Purpose |
|-------|---------|
| `PdfSource` | Registered PDF: source_id, path, SHA-256, title, page count |
| `TocEntry` | Single TOC bookmark: level, title, pdf_page (0-based) |
| `PageLabel` | Page index → printed label mapping |
| `SectionNode` | Node in the canonical section tree: section_id, title, slug, level, parent, children, page ranges, printed labels, output path |
| `SectionTree` | Full tree for one PDF: source_id, nodes dict, root_ids list |
| `ProvenanceRecord` | Artifact provenance: who made it, when, with what tool and config |
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

JSON files stored under `data/artifacts/<source_id>/`:
- `pdf_source.json` — PdfSource model dump
- `toc.json` — list of TocEntry dumps
- `page_labels.json` — list of PageLabel dumps
- `section_tree.json` — full SectionTree dump
- `emit_manifest.json` — section_id → output path mapping

### Cache Semantics

- Each pipeline step checks `StepManifestStore.is_completed()` before running
- If a step's artifact exists and the step is marked completed, it's skipped
- `--force` forces re-run of the current command's step
- `--force-step <step>` forces re-run of a specific step by name
- Config hash comparison is supported for detecting when configuration has changed

## Section ID and Path Generation

### Section IDs

```
<source_id>/<slug-path>
```

Where `slug-path` chains ancestor and child slugs:
- `core-rulebook/chapter-1-introduction`
- `core-rulebook/chapter-1-introduction/overview`
- `core-rulebook/chapter-2-characters/attributes/strength`

### Slug Rules

- Unicode → ASCII via NFKD normalization
- Lowercase
- Parentheses and brackets stripped
- Non-alphanumeric → hyphens
- Multiple hyphens collapsed
- Leading/trailing hyphens stripped

### Output Paths

- Sections **with children** → `<books_dir>/<slug-path>/index.md`
- Sections **without children** → `<books_dir>/<slug-path>.md`

### Frontmatter

Every emitted Markdown file includes:

```yaml
source_pdf: core-rulebook.pdf
source_pdf_id: core-rulebook
section_id: core-rulebook/chapter-02/skills
level: 2
pdf_page_start: 45
pdf_page_end: 53
printed_page_start: 31
printed_page_end: 39
parent_section_id: core-rulebook/chapter-02
aliases: []
tags:
  - rulebook
  - imported
```

## Module Layout

```
src/rulebook_wiki/
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
│   └── build_section_tree.py   # Canonical section tree construction
├── extract/             # (Stub) Future: Marker/OCR integration
├── repair/              # (Stub) Future: repair and normalization
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
3. **LLM usage is constrained and cached.** When LLM steps are added, they must check the cache before calling the model and persist both prompt and response.
4. **Structured intermediates over text-to-text.** The pipeline produces JSON artifacts, not just "PDF in → Markdown out." This enables inspection, debugging, and partial re-runs.
5. **Extraction engine is replaceable.** Marker will likely be the main extractor, but the architecture allows swapping it out. Section-scoped extraction is the integration point.
6. **Multi-PDF from the start.** All identities are namespaced by source_id even though M1 handles one PDF. This prevents painful refactoring later.
7. **Two-layer wiki model (future).** Layer 1: per-source trees preserving the original book structure. Layer 2: global semantic overlay with shared concepts, aliases, and cross-links. No destructive merging.