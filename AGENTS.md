# AGENTS.md — Guide for LLM Coding Agents

## Project Overview

**PDF-to-Wiki** converts pen-and-paper rulebook PDFs into structured Markdown wikis with full traceability from generated Markdown back to source PDF pages. The pipeline extracts TOC/outline, page labels, and section metadata from PDFs, builds a canonical section tree, extracts text content per section (Marker ML or PyMuPDF deterministic), runs repair/normalization, and emits Markdown files with YAML frontmatter.

**Current milestone (M5 ✅):** Cross-book linking and quality features complete. Core pipeline is feature-complete for three large rulebooks (Storypath 257pg/450 sections, CoD 301pg/521 sections, Shadowrun 5E 502pg/544 sections). Glossary extraction, Docling engine, and auto-validate added. Semantic enrichment (entity pages, LLM) deferred to M6.

---

## Before Making Changes

1. **Read `README.md`** for a project summary and quick-start commands.
2. **Read `docs/ARCHITECTURE.md`** to understand the current module layout, data flow, and design constraints.
3. **Read `docs/ROADMAP.md`** to understand what is done, what is in progress, and what is deferred.

Do **not** start coding without this context. The architecture has strong opinions about caching, provenance, deterministic operations, and the role of LLMs.

## Architecture Constraints

These are **non-negotiable** unless explicitly reconsidered:

- **The PDF TOC is the source of truth for hierarchy.** Do not infer heading depth from text styling.
- **Markdown is NOT the only source of truth.** The canonical section tree JSON and the SQLite/JSON artifacts are the primary records.
- **Extraction engines are pluggable.** `BaseEngine` ABC in `extract/` with `@register_engine` decorator. Add new engines by subclassing and decorating.
- **Default engine is Marker** (high quality, ML-powered, ~30s/page). PyMuPDF is the fast fallback (~0.1s/page).
- **Use LLMs only for non-deterministic tasks.** TOC extraction, page counting, slug generation, page-label extraction, Markdown emission, and engine dispatch must remain deterministic. Marker's ML inference is considered a "deterministic-ish" extraction step (cached, not LLM-driven).
- **LLM backend:** Ollama, default model `glm-5.1:cloud`. Cache all LLM calls aggressively.
- **Cache/provenance is built in from the start.** Every expensive step checks the cache before running and records provenance after.
- **Per-step artifacts on disk.** Intermediate results are persisted under the artifact directory.
- **Design for multi-PDF ingestion.** All section IDs are namespaced by `source_id` (e.g., `chronicles-of-darkness/rules/combat`).
- **Standard Markdown relative links** (`[Title](../path/section.md)`) — NOT Obsidian `[[wiki-links]]`.
- **Parent sections clip content** to only pages before their first child's start page, preventing massive duplication.
- **Single-root TOC unwrapping**: When a PDF has one root whose slug matches `source_id`, its children are promoted to root level with slug deduplication.
- **Marker sub-heading absorption**: When splitting Marker output, unclaimed sub-headings (not in the TOC) are absorbed by the parent section. This preserves tables under headings like "Ranged Weapons Chart" inside "Weapons".
- **Preserve backwards compatibility of persisted artifacts** unless intentionally migrating them.

---

## Workflow Conventions

- **Small, reviewable, working increments.** Prefer a correct small change over a large speculative refactor.
- **Keep documentation in sync.** When you change code, update:
  - `docs/ROADMAP.md` (task status, change log)
  - `docs/ARCHITECTURE.md` (if architecture changes)
  - `docs/USAGE.md` (if CLI behavior changes)
  - `AGENTS.md` (if agent-facing conventions change)
- **Run the test suite** before declaring work done: `uv run pytest tests/ -v`
- **Tests must use `engine="pymupdf"`** — Marker requires ML models and takes minutes per test.
- **191 tests passing** — run `uv run pytest tests/ -q` to verify.

---

## Key File Locations

| Path | Purpose |
|------|---------|
| `src/pdf_to_wiki/` | Main package |
| `src/pdf_to_wiki/cli.py` | CLI commands (Click) |
| `src/pdf_to_wiki/models.py` | Canonical Pydantic data models (PdfSource, TocEntry, PageLabel, SectionNode, SectionTree, ProvenanceRecord, StepManifest) |
| `src/pdf_to_wiki/config.py` | Configuration loading (TOML) |
| `src/pdf_to_wiki/ingest/` | PDF ingestion (register, TOC, page labels, section tree, extract) |
| `src/pdf_to_wiki/ingest/register_pdf.py` | PDF registration + SHA-256 fingerprinting |
| `src/pdf_to_wiki/ingest/extract_toc.py` | TOC extraction via PyMuPDF, no-TOC fallback (`_synthesize_toc_from_headings()`) |
| `src/pdf_to_wiki/ingest/extract_page_labels.py` | Page labels via pypdf |
| `src/pdf_to_wiki/ingest/build_section_tree.py` | Section tree: TOC + labels → canonical tree, `_unwrap_single_root()`, `_dedup_slug()`, parent clipping |
| `src/pdf_to_wiki/ingest/extract_text.py` | Extraction orchestration (engine dispatch, caching, `_extract_with_marker()`, `_find_overlapping_siblings()`) |
| `src/pdf_to_wiki/extract/` | Extraction engine framework + engine implementations |
| `src/pdf_to_wiki/extract/__init__.py` | `BaseEngine` ABC, `@register_engine`, `get_engine()`, `list_engines()` |
| `src/pdf_to_wiki/extract/marker_engine.py` | Marker engine: `extract_full_pdf()`, `split_markdown_by_headings()` (3-pass: match/absorb/assemble), `_extract_by_page_range()` |
| `src/pdf_to_wiki/extract/docling_engine.py` | Docling engine: `extract_full_pdf()`, `extract_page_range()` via IBM Docling (`[docling]` optional dep) |
| `src/pdf_to_wiki/extract/pymupdf_engine.py` | PyMuPDF engine: `extract_page_range()`, `extract_page_text_structured()`, `find_heading_position()`, `extract_section_text_structured()` |
| `src/pdf_to_wiki/extract/pdf_images.py` | Image extraction (PyMuPDF), content-hash dedup, reference rewriting |
| `src/pdf_to_wiki/repair/clean_text.py` | Structured extraction: column-aware layout, header/footer removal, soft-hyphen/hard-hyphen repair, paragraph assembly, `clean_marker_artifacts()` (page-anchor spans + page-links), dingbat manifest + remapping |
| `src/pdf_to_wiki/repair/normalize.py` | OCR word-break repair, bullet normalization (TTRPG dot ratings), whitespace normalization, page-ref annotation with `Wordp.N` fix, `<br>`-in-table conversion, running header stripping (`>> CHAPTER <<`) |
| `src/pdf_to_wiki/repair/extract_glossary.py` | Glossary extraction (`**Term —**` lexicon entries, **Term**: inline defs, **Field:** structured fields), glossary.md emission |
| `src/pdf_to_wiki/repair/rewrite_refs.py` | Page-ref annotation (`p. 43` → `{{page-ref:43}}`), rewriting to Markdown relative links, cross-book resolution |
| `src/pdf_to_wiki/emit/markdown_writer.py` | Markdown emission with YAML frontmatter, `_rewrite_asset_paths()` (alt text population), `_filter_sections()`, stale file cleanup |
| `src/pdf_to_wiki/emit/obsidian_paths.py` | Deterministic path generation (slug → directory/file structure) |
| `src/pdf_to_wiki/emit/validate.py` | Post-build validation: broken links, missing images, orphan files, unresolved page refs |
| `src/pdf_to_wiki/cache/` | SQLite cache, artifact store, step manifests |
| `src/pdf_to_wiki/llm/` | (Stub) Future: Ollama-backed enrichment |
| `data/` | Runtime data (cache, artifacts, outputs) — gitignored |
| `tests/` | Test suite (130 tests) |

---

## Critical Implementation Details

### Marker Sub-Heading Absorption (`split_markdown_by_headings`)

Marker often produces sub-headings that aren't in the PDF's TOC (e.g., "Ranged Weapons Chart" inside a "Weapons" section). The splitter uses a **3-pass algorithm**:

1. **Pass 1 (Match):** Find each section's heading in the Marker Markdown, building `section_matches` and `heading_claimed` sets
2. **Pass 2 (Absorb):** For each matched section, extend forward through consecutive unclaimed heading ranges until hitting one claimed by another section
3. **Pass 3 (Assemble):** Build section text from the full range (matched heading through last absorbed heading)

This ensures tables and content under unTOC'd sub-headings aren't lost. Doubling total content from 785K → 1.63M chars on CoD.

### Mid-Page Section Extraction (PyMuPDF Engine)

Some sections start mid-page (e.g., "Services" under a "Social" heading). `find_heading_position()` uses **font-size ≥ 1.3× body text** to detect real headings vs running headers with the same text. Returns `(block_idx, line_idx)` in reading order for two-column PDFs. `extract_page_text_structured(skip_before=...)` skips content before heading at block+line level.

### Single-Root TOC Unwrapping

Many PDFs have one root node whose title matches the book title (e.g., "Chronicles of Darkness" with `source_id=chronicles-of-darkness`). `_unwrap_single_root()` detects this and promotes the root's children to top level. `_dedup_slug()` disambiguates slugs that collide with `source_id` (e.g., `chronicles-of-darkness` → `chronicles-of-darkness-rules`).

### Dingbat Remapping

`extract_dingbat_manifest()` scans the PDF's font data via PyMuPDF to build a per-PDF replacement map. `remap_dingbat_bullets()` uses the manifest when available, with heuristic fallback. This handles custom fonts like FantasyRPGDings where `Y` → `•`.

### Image Extraction & Rewriting

PyMuPDF extracts images from each page to `books/<source_id>/.assets/` as PNG files. Content-hash deduplication prevents duplicate images. Marker's image references (`![_page_N_Picture_X.jpeg]`) are rewritten to note-relative paths (`![](.assets/page_N_picture_X.png)`). Fallback matching handles page-index misalignment between Marker and PyMuPDF.

### No-TOC PDF Fallback

When a PDF has no embedded bookmarks, `extract_toc()` calls `_synthesize_toc_from_headings()` which scans the PDF for text spans with font sizes significantly larger than body text. Heading levels are estimated by relative font size: ≥2.0× body → L1, ≥1.5× → L2, ≥1.3× → L3. Consecutive duplicate headings (running headers) are deduplicated.

### Build-time Validation

The `validate` command checks emitted wikis for broken Markdown links, missing image references, orphan `.md` files, and unresolved `{{page-ref:N}}` annotations. It cross-references the emit manifest against actual files on disk. Reports issues via `ValidationReport` dataclass.

### Selective Processing & Dry-Run

`--sections` filters by section_id, slug, or title substring. `--page-range` restricts to sections overlapping a given page range. `--dry-run` prevents file writes and reports what would be done. Implemented in `emit_skeleton`, `extract_text`, and `build_section_tree`.

---

## CLI Commands

```bash
pdf-to-wiki register <pdf_path>       # Register a PDF source
pdf-to-wiki inspect <source_id>       # Show PDF metadata
pdf-to-wiki toc <source_id>           # Extract/display TOC
pdf-to-wiki page-labels <source_id>   # Extract/display page labels
pdf-to-wiki build-section-tree <source_id>  # Build canonical section tree
pdf-to-wiki extract <source_id>        # Extract text content (--engine marker|pymupdf)
pdf-to-wiki emit-skeleton <source_id> # Emit Markdown skeleton
pdf-to-wiki build <source_id>         # Run full pipeline (6 steps)
pdf-to-wiki build-all                  # Build all registered PDFs + global index
pdf-to-wiki repair <source_id>        # Re-emit with repair/normalization
pdf-to-wiki validate <source_id>       # Check for broken links, missing images, orphans
```

Common flags: `--force`, `--force-step <step>`, `--engine <name>`, `--skip-extract`, `--dry-run`, `--sections <list>`, `--page-range START-END`, `--config <path>`, `--output-dir <dir>`, `--cache-dir <dir>`

---

## Installation

```bash
# CLI tool install (PyMuPDF only — fast, no ML models)
uv tool install pdf-to-wiki

# CLI tool install with Marker
uv tool install "pdf-to-wiki[marker]"

# Development
uv sync --extra dev                          # PyMuPDF only
uv sync --extra dev --extra marker          # With Marker
```

---

## Testing

```bash
# Run all tests (uses pymupdf engine — fast)
uv run pytest tests/ -v

# Run a specific test file
uv run pytest tests/test_extract_text.py -v
```

All tests use `tmp_path` fixtures — no persistent state. **Do not use Marker engine in tests** — it requires ~2GB of ML models and takes minutes.

---

## Adding New Extraction Engines

1. Create a new module in `src/pdf_to_wiki/extract/` (e.g., `docling_engine.py`)
2. Subclass `BaseEngine` from `pdf_to_wiki.extract`
3. Use `@register_engine("name")` decorator
4. Implement `extract_page_range()`, `engine_name`, `engine_version`
5. Import the module in `src/pdf_to_wiki/ingest/extract_text.py` to trigger registration
6. Update `list_engines()` will automatically include it
7. Add the engine name to config docs and CLI help text

---

## When Adding New Pipeline Steps

1. Add a new module in the appropriate subpackage (`ingest/`, `extract/`, `repair/`, `emit/`, `llm/`).
2. Create a Pydantic model for the step's input/output data in `models.py` if needed.
3. Use `CacheDB` and `ArtifactStore` for caching.
4. Use `StepManifestStore` to track step completion.
5. Add a CLI command in `cli.py`.
6. Write tests in `tests/`.
7. Update `docs/ROADMAP.md` and `docs/ARCHITECTURE.md`.