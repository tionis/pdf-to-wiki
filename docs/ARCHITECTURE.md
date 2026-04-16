# Architecture

## Overview

PDF-to-Wiki is a **coordinator pipeline** that converts pen-and-paper rulebook PDFs into structured Markdown wikis. PDF → wiki is treated as a sequence of stages with persisted intermediate artifacts. Each stage reads from and writes to the canonical artifact store, and every expensive step is cacheable and resumable.

## Pipeline Stages

```
┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Register │ →  │   TOC    │ →  │  Page Labels  │ →  │ Section  │ →  │ Extract  │ →  │   Emit   │
│   PDF    │    │Extract   │    │   Extract     │    │   Tree   │    │   Text   │    │ Markdown │
│          │    │          │    │               │    │          │    │(engine)  │    │  Notes   │
└──────────┘    └──────────┘    └──────────────┘    └──────────┘    └──────────┘    └──────────┘
     │               │                │                   │               │               │
     └───────────────┴────────────────┴───────────────────┴───────────────┴───────────────┘
                            SQLite Cache + JSON Artifacts
```

After emission, the **repair pipeline** can re-emit with OCR repair, bullet normalization, page-ref annotation/rewriting, heading deduplication, and Marker artifact cleanup.

### Stage Details

1. **Register** — Fingerprint the PDF (SHA-256), extract basic metadata (title, page count), derive `source_id`, persist `PdfSource` in SQLite and as JSON artifact.
2. **TOC Extract** — Extract the PDF's embedded bookmarks/outline via PyMuPDF. Normalize page numbers to 0-based. When a PDF has no embedded bookmarks, fall back to font-size heading detection (`_synthesize_toc_from_headings()`). Persist as JSON artifact.
3. **Page Labels Extract** — Extract printed page labels (Roman numerals, Arabic numbers) via pypdf's `page_labels` property. Fall back to 1-indexed numeric labels if no `/PageLabels` dict. Persist as JSON artifact.
4. **Section Tree** — Build a canonical tree of `SectionNode` objects from the TOC + page labels. Compute page ranges, parent-child relationships, section IDs. **Single-root unwrapping**: if the tree has one root matching `source_id`, promote its children and deduplicate slugs. **Parent clipping**: parent sections only include pages before their first child's start page. Persist as JSON artifact.
5. **Extract Text** — Extract text content using a pluggable extraction engine. **Marker** (default): ML-powered, produces clean Markdown with columns/tables/bold-italic. Full-PDF conversion cached as `marker_full_md.md`, then split by headings with sub-heading absorption. **PyMuPDF** (fallback): deterministic, column-aware with header/footer removal, font-size-based heading detection for mid-page sections. Sections without heading matches fall back to PyMuPDF per-page extraction. Persist as JSON artifact.
6. **Emit Notes** — Generate Markdown files from the section tree. Each section with children becomes a directory with `index.md`; leaf sections become individual `.md` files. YAML frontmatter includes source_pdf (portable: `filename.pdf (sha256:hash)`), page ranges, printed labels. Relative Markdown links between sections. Image references rewritten to note-relative `.assets/` paths. Stale file cleanup on re-emission. Persist an emit manifest.

### Repair Pipeline (post-emission)

The `repair` command re-emits Markdown with the following transformations applied:

1. **OCR word-break repair** — Fix hyphenated line breaks from PDF extraction (suffix heuristic + English word pairs)
2. **Bullet normalization** — Convert •, ◦, ▪ to Markdown `-`; preserve TTRPG dot ratings (`••` → `- •`)
3. **Whitespace normalization** — Collapse excessive blank lines, strip trailing whitespace
4. **Page reference annotation** — `p. 43` → `{{page-ref:43}}`
5. **Page reference rewriting** — `{{page-ref:43}}` → `[Section Title](../path/section.md)` using section tree lookup (cross-book)
6. **Duplicate heading deduplication** — Remove headings matching section title
7. **Marker artifact cleanup** — Strip `<span id="page-N-M">` page anchors and `[\(p.21\)](#page-21-0)` page-links
8. **<br> in tables** — Convert `<br>` in pipe tables to ` / ` for broad Markdown compatibility
9. **Joined page refs** — Separate joined game-term + page-ref patterns (e.g., `Parkourp. 48` → `Parkour p. 48`) before annotation
10. **Running header stripping** — Remove `>> CHAPTER NAME <<` patterns (Shadowrun/Catalyst Game Labs PDFs) from extracted text
11. **Glossary extraction** — Regex-based extraction of **Term —** definitions from lexicon sections and **Term**: definitions from inline text, with structured field extraction (**Effect:**, **Prerequisites:**, etc.) as separate records

### Validation Pipeline (post-build)

The `validate` command checks the emitted wiki for issues:

1. **Broken Markdown links** — `[Title](path.md)` references that don't resolve to existing files
2. **Broken image references** — `![](.assets/img.png)` where the image doesn't exist
3. **Orphan .md files** — Files in the output directory not in the emit manifest
4. **Unresolved page refs** — `{{page-ref:N}}` annotations left in the text after repair

### No-TOC Fallback

When a PDF has no embedded bookmarks, `extract_toc()` automatically falls back to font-size heading detection via `_synthesize_toc_from_headings()`. This scans the PDF for text spans with font sizes significantly larger than body text and creates synthetic TOC entries with estimated heading levels (≥2.0× body → L1, ≥1.5× → L2, ≥1.3× → L3).

## Extraction Engine Architecture

### BaseEngine ABC (`extract/__init__.py`)

All extraction engines implement:
- `extract_page_range(pdf_path, start_page, end_page, start_heading=None) -> str`
- `engine_name -> str` (for provenance)
- `engine_version -> str` (for provenance)

Engines are registered via `@register_engine("name")` decorator and instantiated via `get_engine("name", config)`.

### Marker Engine (`extract/marker_engine.py`)

- Uses `marker-pdf` library with layout recognition, OCR error detection, bbox detection, text recognition, table recognition
- Models downloaded on first use (~2GB), cached in `~/.cache/datalab/models/`
- `extract_full_pdf()`: Converts entire PDF in one pass (most efficient)
- `split_markdown_by_headings()`: **3-pass algorithm** splits full-PDF Markdown into per-section content:
  - **Pass 1 (Match):** Find each section's heading, track claimed heading ranges
  - **Pass 2 (Absorb):** Extend matched sections forward through consecutive unclaimed heading ranges (preserves tables under sub-headings like "Ranged Weapons Chart")
  - **Pass 3 (Assemble):** Build section text from full range
- `_extract_by_page_range()`: Fallback using `<span id="page-N-X">` anchors
- Consecutive same-title headings are merged (Marker sometimes emits heading twice: once for table, once for body)
- Performance: ~30s/page on CPU (6.5h for 301 pages), one-time cost with caching

### PyMuPDF Engine (`extract/pymupdf_engine.py`)

- Uses PyMuPDF dict-mode extraction with column-aware layout handling
- `extract_page_text_structured(skip_before=(block_idx, line_idx))`: Skips content before a heading position for mid-page section starts
- `find_heading_position(page, title)`: Font-size-based heading detection (≥1.3× body text) for mid-page splits
- `extract_section_text_structured(start_heading=...)`: Extracts only from heading onward on first page, preserving full multi-page content
- Dingbat manifest: `extract_dingbat_manifest()` builds per-PDF font replacement map
- Performance: ~0.1s/page (no ML models)
- Table detection: `config.extract_tables = true` (default) — detects tables via `find_tables()` and appends Markdown pipe-tables to page text. In-place replacement is a future enhancement.

### Engine Selection

- Config: `extract.engine = "marker"` (default), `"pymupdf"`, or `"docling"`
- CLI: `--engine marker`, `--engine pymupdf`, or `--engine docling`
- Unknown engines fall back to pymupdf with a warning
- Docling requires `pip install pdf-to-wiki[docling]`; not registered if not installed

### Glossary and Entity Pipeline

- Glossary extraction (`repair/extract_glossary.py`): regex-based extraction of **Term —** definitions from lexicon sections, **Term**: inline definitions, **Field:** structured fields
- Glossary emission: `books/<source_id>/glossary.md` with alphabetical index and section links
- Entity page generation (`emit/entity_pages.py`): cross-reference stub pages under `entities/` namespace with see-also links to related terms
- Entity index: `entities/index.md` with alphabetical letter navigation
- Glossary is auto-enabled for Marker/Docling engines (which preserve bold/italic); `--glossary` flag on `build` to force
- Entity link injection: `config.inject_entity_links = true` (default) — after glossary is loaded, section text is scanned for term references and plain occurrences replaced with `[Term](../entities/term.md)` links. Two-pass algorithm avoids position shifting. Skips headings, bold terms, existing links.

### Marker Full-PDF Caching Strategy

1. Convert entire PDF in one Marker call → `marker_full_md.md` artifact
2. Split Markdown by headings with sub-heading absorption → per-section content
3. Sections without heading matches → PyMuPDF fallback
4. On re-run, cached `marker_full_md.md` is reused (no re-conversion)

### Image Pipeline

- PyMuPDF extracts images per page → `extract_pdf_images()` in `pdf_images.py`
- Images saved as PNG to `books/<source_id>/.assets/` (hidden directory per book)
- Content-hash deduplication prevents duplicate images across pages
- Marker image references (`![_page_N_Picture_X.jpeg]`) rewritten to note-relative paths during emission
- Fallback matching for page-index misalignment between Marker and PyMuPDF

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
- **Parent sections clip content** to only pages before their first child's start page — prevents duplication
- **Single-root TOC unwrapping** promotes children when one root matches source_id, with slug deduplication

## Caching and Provenance

### SQLite Cache (`cache.db`)

Three tables:
- `pdf_sources` — registered PDF metadata (PK: source_id)
- `step_manifests` — per-step status tracking (PK: source_id + step)
- `provenance` — artifact provenance records (PK: artifact_id)

### Filesystem Artifacts

Files stored under `data/artifacts/<source_id>/`:

| File | Content |
|------|---------|
| `pdf_source.json` | PdfSource model dump |
| `toc.json` | List of TocEntry dumps |
| `page_labels.json` | List of PageLabel dumps |
| `section_tree.json` | Full SectionTree dump (nodes dict + root_ids) |
| `marker_full_md.md` | Marker's cached full-PDF Markdown output (~1.2MB for CoD) |
| `extract_text.json` | section_id → extracted text mapping (~860KB for CoD) |
| `pdf_images.json` | Image metadata: page, hash, filename, dimensions |
| `dingbat_manifest.json` | Per-PDF font → replacement map |
| `emit_manifest.json` | section_id → output path mapping |

### Cache Semantics

- Each pipeline step checks `StepManifestStore.is_completed()` before running
- If a step's artifact exists and the step is marked completed, it's skipped
- `--force` forces re-run of the current command's step
- `--force-step <name>` forces re-run of a specific step
- `--engine <name>` selects the extraction engine (Marker is default)

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
│   ├── extract_text.py  # Text extraction orchestration (engine dispatch, caching, overlapping siblings)
│   └── build_section_tree.py   # Section tree: single-root unwrapping, slug dedup, parent clipping
├── extract/
│   ├── __init__.py      # BaseEngine ABC, engine registry
│   ├── pymupdf_engine.py # PyMuPDF engine (font-size heading detection, structured extraction, dingbats)
│   ├── marker_engine.py  # Marker engine (full-PDF conversion, 3-pass heading split)
│   └── pdf_images.py     # Image extraction, dedup, reference rewriting
├── repair/
│   ├── clean_text.py    # Structured extraction + cleaning + Marker artifact cleanup
│   ├── normalize.py      # OCR repair, bullets, whitespace
│   └── rewrite_refs.py   # Page-ref annotation/rewriting to Markdown links
├── emit/
│   ├── markdown_writer.py  # Markdown emission (frontmatter, asset paths, stale cleanup, section/page filters)
│   ├── obsidian_paths.py   # Deterministic path generation
│   └── validate.py         # Post-build validation (broken links, orphan files, missing images)
├── llm/                 # (Stub) Future: Ollama-backed enrichment
├── cache/
│   ├── db.py            # SQLite cache database
│   ├── artifact_store.py # Filesystem artifact storage
│   └── manifests.py     # Step manifest tracking
└── index/               # Global catalog and link graph
```

## Output Structure

```
data/outputs/wiki/
├── books/
│   ├── index.md                    # Global wiki index (links to all books)
│   ├── chronicles-of-darkness/
│   │   ├── index.md               # Per-book index
│   │   ├── .assets/               # Images (hidden dir, PNG files)
│   │   │   ├── page_2_picture_0.png
│   │   │   └── ...
│   │   ├── apt-3b.md             # Leaf section → single .md file
│   │   ├── chronicles-of-darkness-rules/   # Parent section → directory
│   │   │   ├── index.md
│   │   │   ├── infernal-engines-dramatic-systems/
│   │   │   │   ├── index.md
│   │   │   │   ├── violence/
│   │   │   │   │   ├── index.md
│   │   │   │   │   └── weapons-and-armor.md
│   │   │   │   └── ...
│   │   │   └── ...
│   │   ├── the-god-machine-chronicle/
│   │   │   └── ...
│   │   └── the-appendices/
│   │       ├── index.md
│   │       ├── appendix-one-equipment/
│   │       │   ├── index.md
│   │       │   ├── weapons.md          # Contains Ranged & Melee weapon tables
│   │       │   ├── services.md         # Contains Services table
│   │       │   └── ...
│   │       └── ...
│   └── storypath-ultra-core-manual-final-download/
│       └── ...
```

## Design Decisions

1. **TOC is the source of truth for hierarchy.** PDF layout inference can be wrong; embedded bookmarks are more reliable for chapter structure.
2. **Deterministic operations use no LLM.** TOC extraction, page counting, slug generation, page-label extraction, and Markdown emission are deterministic.
3. **LLM usage is constrained and cached.** When LLM steps are added, they must check the cache before calling the model.
4. **Structured intermediates over text-to-text.** The pipeline produces JSON artifacts, not just "PDF in → Markdown out." This enables inspection, debugging, and partial re-runs.
5. **Extraction engines are pluggable.** Marker is the default for quality; PyMuPDF is the fast fallback. New engines (Docling, OCR) can be added via `@register_engine`.
6. **Marker output is cached at the full-PDF level.** A single Marker call converts the entire PDF; the result is cached as `marker_full_md.md` and split into sections on subsequent runs.
7. **Multi-PDF from the start.** All identities are namespaced by source_id. Cross-book page references are resolved by searching all loaded section trees.
8. **Standard Markdown relative links** — not Obsidian `[[wiki-links]]`. Works in GitHub, GitLab, VS Code, and any CommonMark renderer.
9. **Marker sub-headings are absorbed** — When Marker creates headings not in the PDF's TOC (e.g., "Ranged Weapons Chart" inside "Weapons"), the 3-pass splitting algorithm absorbs them into the parent section rather than orphaning the content.
10. **Parent sections are clipped** — Parents only include content from pages before their first child starts, preventing massive duplication in the wiki output.
11. **Portable frontmatter** — `source_pdf` uses `filename.pdf (sha256:hash)` instead of absolute filesystem paths, making wikis portable across machines.
12. **Two-layer wiki model (future).** Layer 1: per-source trees preserving the original book structure. Layer 2: global semantic overlay with shared concepts and cross-links.
13. **No-TOC PDF fallback.** When a PDF has no embedded bookmarks, font-size heading detection synthesizes a TOC automatically.
14. **Image alt text from context.** Empty image alt text is populated from the section title for accessibility.
15. **HTML `<br>` in tables.** Converted to ` / ` for broad Markdown compatibility — works in GitHub, GitLab, and CommonMark renderers.
16. **Joined game-term + page refs.** When a capitalised game term runs into a page reference (e.g., `Parkourp. 48`), the space is inserted so the standard page-ref regex can match.