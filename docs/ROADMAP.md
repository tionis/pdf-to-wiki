# Roadmap

Build a pipeline that ingests pen-and-paper rulebook PDFs and produces a structured Obsidian-compatible Markdown wiki, preserving full traceability from generated Markdown back to source PDF pages.

---

## Current Status

**Milestone 5 complete.** The pipeline is feature-complete for production use. It processes full rulebook PDFs through TOC extraction, section tree construction, text extraction (Marker, PyMuPDF, or Docling), repair/normalization, glossary extraction, entity page generation, entity link injection, and Markdown emission — with auto-validation. Tables are preserved via Marker's native pipe-table output or PyMuPDF's `find_tables()` with in-place replacement. Three extraction engines at three price points: PyMuPDF (~0.1s/page), Docling (~1-5s/page), Marker (~30s/page). Multiple PDFs can be ingested into a shared wiki with proper namespacing. Internal links use standard Markdown relative links for broad compatibility.

**Tested on three large rulebooks:**
- **Storypath Ultra Core Manual** (257 pages, 450 sections, 9 tables)
- **Chronicles of Darkness** (301 pages, 521 sections, 37 table sections, 1.63M chars)
- **Shadowrun 5E Core Rulebook** (502 pages, 544 sections, 3-level deep TOC, 2.66M chars)

**270 tests passing.**

---

## Milestones

### Milestone 1 — TOC-driven Markdown tree for one PDF ✅

- [x] PDF registration and fingerprinting
- [x] TOC extraction via PyMuPDF
- [x] Page-label extraction via pypdf
- [x] Canonical section tree data structures and persistence
- [x] Deterministic Markdown skeleton emission with YAML frontmatter
- [x] SQLite cache/provenance store
- [x] Filesystem artifact store for intermediate JSON
- [x] Step manifest tracking with --force/--force-step
- [x] CLI commands: register, inspect, toc, page-labels, build-section-tree, emit-skeleton, build
- [x] Test suite (60 tests passing initially)
- [x] Project documentation (README, ARCHITECTURE, USAGE, AGENTS, ROADMAP)

### Milestone 2 — Structured text extraction for one PDF ✅

- [x] Pluggable extraction engine architecture (`BaseEngine` ABC + registry)
- [x] PyMuPDF engine: deterministic, no models, column-aware layout + header/footer removal
- [x] Marker engine: ML-powered, handles columns/tables/images/bold-italic, ~30s/page on CPU
- [x] Config-driven engine selection (`extract.engine = "marker"` or `"pymupdf"`)
- [x] CLI `--engine` flag to override per-run (`pdf-to-wiki extract SRC --engine pymupdf`)
- [x] Full-PDF Marker conversion with single-pass caching (`marker_full_md.md` artifact)
- [x] Heading-based section splitting from Marker's Markdown output
- [x] Sub-heading absorption: unTOC'd Marker sub-headings absorbed by parent section
- [x] Fallback to PyMuPDF for sections without heading matches
- [x] Text cleaning pipeline: soft-hyphen removal, hard-hyphen rejoin, paragraph assembly, page-number stripping, header/footer detection and removal
- [x] Mid-page section extraction via font-size-based heading detection
- [x] 85 tests passing
- [x] Provenance tracking records engine name and version

### Milestone 3 — Repair and normalization ✅

- [x] OCR word-break repair (suffix-based heuristic + specific English word pairs)
- [x] Exclusion list for false-positive preventions ("much less" not joined)
- [x] Bullet list normalization (•, ◦, ▪ → Markdown `-`; dot ratings `••` preserved as `- •`)
- [x] Dingbats font mapping (FantasyRPGDings `Y` → `•`, ZapfDingbats, Symbol)
- [x] Dingbat remapping via PyMuPDF font manifest (per-PDF replacement map from actual font data)
- [x] Whitespace normalization (collapse excessive blank lines, strip trailing)
- [x] Page reference annotation (`p. 43` → `{{page-ref:43}}`)
- [x] Page reference rewriting to Markdown relative links (`[Title](../path/section.md)`)
- [x] Cross-book page reference resolution (search other section trees when current tree doesn't match)
- [x] Duplicate heading deduplication (leading and mid-content headings matching section title)
- [x] Marker artifact cleanup (page-anchor `<span>` tags stripped)
- [x] Marker page-link unwrapping (`[\(p.21\)](#page-21-0)` → plain text before page-ref annotation)
- [x] `repair` CLI command (re-emits with repair applied)
- [x] 115 tests passing
- [ ] OCR fallback for problematic pages (dropped — Marker/Docling have built-in OCR)
- [ ] LLM-assisted structural disambiguation (dropped from roadmap — deterministic pipeline sufficient)

### Milestone 4 — Multi-PDF wiki ingestion ✅

- [x] Support multiple PDFs in one shared wiki
- [x] Namespace PDFs under `books/<source_id>/` directory structure
- [x] Collision avoidance via source_id namespacing (section IDs are `source_id/chapter/section`)
- [x] Global top-level wiki index (`books/index.md`) linking to all registered books
- [x] Per-book index note with relative Markdown links to chapters
- [x] Per-source provenance preservation in cache DB
- [x] CLI: `pdf-to-wiki build-all` (builds all registered PDFs + global index)
- [x] Single-root TOC unwrapping with slug deduplication (`_unwrap_single_root()`)
- [x] Parent section content clipping (pages before first child only)
- [x] Portable source_pdf frontmatter (`filename.pdf (sha256:hash)` instead of absolute path)
- [ ] Configurable output structure (dropped — nested structure works well, no use case for flat)

### Milestone 5 — Cross-book linking and semantic enrichment ✅

- [x] Intra-book reference rewriting (page → section → Markdown relative link)
- [x] Cross-book page reference resolution (all_trees parameter)
- [x] Standard Markdown relative links (not Obsidian wiki-links) for broad compatibility
- [x] Table preservation via Marker's native Markdown pipe-table output
- [x] Sub-heading absorption for table content (e.g., Weapons → Ranged/Melee Charts)
- [x] Duplicate heading merge in Marker's section splitting
- [x] Image extraction from PDF and saving to `books/<source_id>/.assets/` hidden directory
- [x] Image reference rewriting (Marker refs → note-relative paths, fallback matching, dedup by content hash)
- [x] Marker artifact cleanup (page-anchor spans and page-links stripped)
- [x] Repair pipeline: handle `Wordp. N` pattern (joined game term + page ref)
- [x] HTML `<br>` in Marker table output → converted to ` / `
- [x] Build-time validation: `validate` CLI command (broken links, orphan files, missing images)
- [x] Image alt text from section title context
- [x] No-TOC PDF fallback (font-size heading detection)
- [x] `--dry-run` mode
- [x] `--sections` and `--page-range` filters
- [x] Running header stripping (`>> CHAPTER <<` pattern for Shadowrun/Catalyst PDFs)
- [x] Glossary extraction from bold/italic game terms (lexicon sections + inline definitions)
- [x] Structured field extraction (**Effect:**, **Prerequisites:**, etc.)
- [x] Docling engine integration (`[docling]` optional dep, `@register_engine("docling")`)
- [x] Auto-validate on build (run validation after build, `--no-validate` to skip)
- [x] Entity page generation (cross-reference stubs from glossary, `entities/` namespace + index)
- [x] Glossary wired into `build` pipeline (`--glossary` flag, auto-enabled for Marker/Docling engines)
- [x] PyMuPDF table extraction wiring (`config.extract_tables = true`, Tech debt #6 resolved)
- [x] Entity link injection (`inject_entity_links`, config: `inject_entity_links = true`)
- [x] BlobForge import (`import-blobforge` CLI, reuse distributed Marker output)
- [x] 281 tests passing

---

## Tasks

### Completed

- [x] Project skeleton: pyproject.toml, package structure, CLI entrypoint
- [x] Project rename: rulebook-wiki-pipeline → pdf-to-wiki (CLI binary, package, config filenames)
- [x] `uv`-based install/dev docs; `[marker]` optional dependency group in pyproject.toml
- [x] Config loading from TOML with defaults
- [x] Canonical data models (PdfSource, TocEntry, PageLabel, SectionNode, SectionTree, ProvenanceRecord, StepManifest)
- [x] SHA-256 fingerprinting and source_id derivation
- [x] PDF registration with metadata extraction
- [x] TOC extraction via PyMuPDF with caching
- [x] Page-label extraction via pypdf
- [x] Section tree construction from TOC + page labels
- [x] Single-root TOC unwrapping with slug deduplication
- [x] Deterministic slug generation (strip parentheses/brackets)
- [x] Markdown skeleton emission with YAML frontmatter
- [x] Portable source_pdf frontmatter (filename + sha256, not absolute path)
- [x] Book-level index notes with relative Markdown links to chapters
- [x] Global wiki index linking all registered books
- [x] SQLite cache/provenance store and filesystem artifacts
- [x] Step manifest tracking (running → completed/failed)
- [x] --force and --force-step CLI options
- [x] `build` command for full pipeline execution
- [x] `build-all` command for multi-PDF batch processing
- [x] `repair` command for re-emission with repair applied
- [x] Text extraction via PyMuPDF (baseline)
- [x] Text extraction via Marker (high-quality ML engine)
- [x] Structured text cleaning (soft-hyphen, hard-hyphen, headers/footers, paragraphs)
- [x] Dingbats/font-aware character remapping (heuristic + font manifest)
- [x] Pluggable extraction engine (Marker + PyMuPDF)
- [x] Full-PDF Marker conversion with caching
- [x] Heading-based Markdown section splitting with duplicate-heading merge
- [x] Sub-heading absorption for unTOC'd Marker sub-headings (3-pass split algorithm)
- [x] Mid-page section extraction via font-size-based heading detection
- [x] Parent section content clipping to prevent duplication
- [x] OCR word-break repair pipeline
- [x] Bullet normalization with TTRPG dot-rating preservation
- [x] Page reference annotation and rewriting to Markdown relative links
- [x] Marker page-link unwrapping (`[(p.21)](#page-21-0)` stripped before page-ref annotation)
- [x] Section tree namespace layout (books/<source_id>/chapter/...)
- [x] Table preservation via Marker's native Markdown pipe-table output
- [x] Marker page-anchor span cleanup
- [x] Image extraction from PDF → `books/<source_id>/.assets/` hidden directory
- [x] Image reference rewriting (Marker refs → note-relative paths, fallback matching, dedup by content hash)
- [x] Stale output cleanup (remove orphan files on re-emission)
- [x] Page-range fallback for unmatched sections (98.9% heading match rate: 515/521 sections)
- [x] 151 tests passing
- [x] Repair: handle `Wordp. N` pattern (joined game term + page ref → insert space before `p.`)
- [x] HTML `<br>` in Marker pipe tables → converted to ` / ` for broad Markdown compatibility
- [x] `--dry-run` CLI flag: print what would be done without writing files
- [x] `--sections` and `--page-range` CLI filters for selective emission
- [x] `validate` CLI command: check broken links, missing images, orphan files, unresolved page refs
- [x] No-TOC PDF fallback: font-size heading detection synthesizes TOC from PDF content
- [x] Image alt text populated from section title for accessibility
- [x] Running header stripping (`>> CHAPTER <<` pattern removal for Shadowrun/Catalyst PDFs)
- [x] Shadowrun 5E Core Rulebook added to test corpus (502 pages, 544 sections, 3-level TOC)
- [x] Glossary extraction from bold/italic game terms (62 entries from CoD Lexicon, structured fields separately extracted)
- [x] Structured field extraction (**Effect:**, **Prerequisites:**, etc. — 995 records from CoD)
- [x] Docling engine integration (`[docling]` optional dep group, `@register_engine("docling")`)
- [x] Auto-validate on build (run validation after build, `--no-validate` to skip)
- [x] 191 tests passing (36 new glossary tests)

### Next

- [x] Heading repair (extractor vs TOC disagreement)
  - ✅ Pass 1b fuzzy matching: Jaccard token similarity, page-proximity bonus,
    prefix/suffix stripping (`_strip_heading_affixes()`, `_estimate_heading_pages()`).
  - Rejected if fuzzy score < 0.5.
  - 5 new tests.

- [x] Roman-numeral front-matter detection
  - ✅ `_detect_roman_numerals()` heuristic in `extract_page_labels.py`.
  - Scans first N pages for consecutive Roman numeral page numbers.
  - Integrates as fallback #3 in `_compute_page_labels()`.
  - 5 new tests.

- [x] Sub-heading depth limit for absorption
  - ✅ `max_absorb_depth` parameter (default: 3) in `split_markdown_by_headings()`.
  - Config setting: `sub_heading_absorb_depth`.
  - 3 new tests.

- [x] Structured table data extraction (JSON output for stat/gear tables)
  - ✅ New module: `src/pdf_to_wiki/repair/structured_tables.py`.
  - `parse_pipe_table()`, `extract_pipe_tables()`, `extract_structured_tables()`.
  - CLI: `pdf-to-wiki tables SOURCE_ID [--min-rows N] [--min-cols N] [--csv]`.
  - `PipeTable.to_dict()`, `PipeTable.to_csv()` for export.
  - 20 new tests.

- [x] Font/encoding diagnostics utility
  - ✅ New module: `src/pdf_to_wiki/ingest/diagnostics.py`.
  - CLI: `pdf-to-wiki diagnose SOURCE_ID [--pages P-R] [--json]`.
  - Reports font usage, character frequencies, suspicious chars, symbol fonts.
  - 6 new tests.

- [x] Full Marker build on Shadowrun 5E
  - ✅ Build complete: 502 pages, 544 sections, 5.58M chars, 141 table sections, 312 structured tables, 26 glossary entries, 4493 images, 0 validation issues.
  - 24 sections fell back to PyMuPDF (95.6% heading match rate, up from 98.9% on CoD).
  - Marker full-PDF MD: 5.26M chars cached.

### Dropped (out of scope or no longer needed)

These items were evaluated and removed from the roadmap:

- ~~Design extraction artifact schema~~ — The raw-text `extract_text.json` already supports
  glossary extraction, entity detection, and link injection. A fully structured schema
  (paragraphs, bold/italic spans, etc.) doesn't unlock anything we don't already have.
- ~~OCR fallback via OCRmyPDF~~ — No test PDFs are scanned. Marker and Docling both have
  built-in OCR layers if needed. A separate OCRmyPDF dependency has no current use case.
- ~~LLM-assisted structural disambiguation~~ — The deterministic pipeline already handles
  glossary, entity pages, and link injection. LLM enrichment is a fundamentally different
  product (non-deterministic, requires Ollama infra). Removed from this roadmap.
- ~~Obsidian search index generation~~ — Output is standard Markdown with relative links;
  search indexing is the consumer's job (Obsidian, GitHub, VS Code all build their own).
- ~~Section anchors for reference rewriting~~ — `[Title](../path/section.md)` links already
  work. Deep-link anchors within a section are a nice-to-have with no concrete use case.
- ~~Configurable output structure (flat vs. nested)~~ — The nested `books/source_id/chapter/`
  structure works well for all 3 test books. No one has requested flat output.
- ~~Configurable split depth~~ — Per-section note granularity is what makes the wiki
  browsable. Coarse splitting loses content isolation. No concrete use case.

---

## Open Questions

1. ~~Marker vs Docling~~: ✅ Resolved — both are pluggable engines. Docling is ~5-10x faster but has different output tradeoffs.
2. **Page-label robustness**: ✅ Resolved — Roman-numeral front-matter heuristic detection added as fallback #3. Handles PDFs with no `/PageLabels` dict that use i/ii/iii... numbering.
3. ~~Entity extraction approach~~: ✅ Resolved — deterministic bold/italic pattern extraction via `extract_glossary.py` + entity pages.
4. ~~PyMuPDF table extraction~~: ✅ Resolved — wired into PyMuPDF engine via `config.extract_tables = true` with in-place replacement.
5. **Sub-heading depth limit**: ✅ Resolved — `max_absorb_depth` parameter (default: 3) added to `split_markdown_by_headings()`. Configurable via `sub_heading_absorb_depth` setting.

---

## Technical Debt

1. **CacheDB connection management**: Opens/closes per command. Fine for CLI use; would need a connection pool only if run as a long-lived service. Low priority.
2. **Marker singleton**: `_marker_converter` and `_model_dict` are process-level singletons; not thread-safe. Same as #1 — fine for CLI.
3. ~~No dry-run mode~~: ✅ Added.
4. ~~No `--sections` filter~~: ✅ Added.
5. ~~Old output cleanup~~: ✅ Fixed.
6. ~~table_extract.py not wired~~: ✅ Fixed — PyMuPDF engine uses `find_tables()` with in-place replacement via `replace_tables_in_text()`.
7. ~~6 sections with <50 chars~~: Won't fix — narrative NPC entries, not rules content.
8. ~~~30s/page Marker latency~~: Resolved — Docling engine provides ~1-5s/page alternative. Three engines now at three price points (pymupdf ~0.1s, docling ~1-5s, marker ~30s).
9. ~~validate command doesn't run automatically~~: ✅ Fixed.

---

## Change Log

### 2025-04-19 — BlobForge import, 281 tests

- BlobForge import command (`pdf-to-wiki import-blobforge`):
  - Import Marker output from BlobForge distributed conversion system
  - Places `content.md` as `marker_full_md.md` in artifact store
  - Pipeline skips the expensive Marker conversion when cached output exists
  - Accepts `--zip` (BlobForge conversion zip) or `--markdown` (bare content.md)
  - `--build` flag runs full pipeline after import
  - `--force` overwrites existing marker artifacts
  - `--glossary` / `--no-validate` pass through to build
  - Extracts images from zip to `books/<source_id>/.assets/`
  - Saves BlobForge `info.json` as `blobforge_info.json` artifact
  - `import_from_s3()` for direct S3 download (requires blobforge package)
  - New module: `src/pdf_to_wiki/ingest/import_blobforge.py`
  - 11 new tests (281 total)

- Full Marker build on Shadowrun 5E:
  - 502 pages, 544 sections, 5.58M chars, 141 table sections
  - 312 structured tables extracted, 26 glossary entries, 4,493 images
  - 0 validation issues
  - 24 sections fell back to PyMuPDF (95.6% heading match rate)

### 2025-04-19 — Roadmap items implemented, 270 tests

- Sub-heading depth limit for Marker heading absorption:
  - `max_absorb_depth` parameter (default: 3) in `split_markdown_by_headings()`
  - Configurable via `sub_heading_absorb_depth` setting
  - Prevents pathological over-absorption of deeply nested sub-headings
  - 3 new tests

- Roman-numeral front-matter detection:
  - `_detect_roman_numerals()` heuristic in `extract_page_labels.py`
  - Scans first 30 pages for consecutive Roman-numeral page numbers (i, ii, iii...)
  - Integrates as fallback #3 in `_compute_page_labels()` (after pypdf, manual /PageLabels)
  - `_is_roman_numeral()` and `_roman_to_int()` helper functions
  - Handles pre-Roman cover pages with 'pre-N' labels
  - 5 new tests

- Heading repair (extractor vs TOC disagreement):
  - Pass 1b fuzzy matching in `split_markdown_by_headings()`
  - Jaccard token similarity for word-overlap matching
  - Page-proximity bonus using Marker `<span id="page-N-M">` anchors
  - `_strip_heading_affixes()` strips common prefixes (the, chapter, section, etc.)
  - `_estimate_heading_pages()` maps heading positions to PDF page numbers
  - Rejected if fuzzy score < 0.5 minimum threshold
  - 5 new tests

- Font/encoding diagnostics utility:
  - New module: `src/pdf_to_wiki/ingest/diagnostics.py`
  - `diagnose_fonts()` scans PDF pages, reports font usage, character frequencies
  - Detects suspicious chars (control codes, private-use-area, replacement chars)
  - Identifies symbol/dingbat fonts, per-page font usage summary
  - CLI: `pdf-to-wiki diagnose SOURCE_ID [--pages P-R] [--json]`
  - 6 new tests

- Structured table data extraction:
  - New module: `src/pdf_to_wiki/repair/structured_tables.py`
  - `parse_pipe_table()`: Markdown pipe table → `PipeTable` dataclass with headers + rows
  - `extract_pipe_tables()`: find all tables in Markdown text, capture captions
  - `extract_structured_tables()`: full pipeline extraction from section data
  - Handles: alignment markers, empty cells, duplicate headers, `<br>` normalization
  - `PipeTable.to_dict()` and `PipeTable.to_csv()` for JSON/CSV export
  - CLI: `pdf-to-wiki tables SOURCE_ID [--min-rows N] [--min-cols N] [--csv]`
  - 20 new tests

- Roadmap cleanup: removed 7 stale/out-of-scope items, closed 2 tech debts
- 270 tests passing (39 new)

### 2025-04-18 — Entity link injection, 231 tests

- Entity link injection (`inject_entity_links()` in `entity_pages.py`):
  - Scans section text for glossary term occurrences
  - Replaces plain text with `[Term](entities/term.md)` links
  - Two-pass algorithm: collect candidates → replace from end-to-start
  - Smart avoidance: skips headings, bold definitions, existing links, overlapping terms
  - Longest-match-first priority (\"dice pool\" linked before \"dice\")
  - Max 20 links per section (configurable)
  - Config: `inject_entity_links = true` (default)
  - Integrated into Markdown emission pipeline
- 12 new injection tests (231 total)

### 2025-04-18 — Entity pages, glossary in build, PyMuPDF tables

- Entity page generation (`src/pdf_to_wiki/emit/entity_pages.py`):
  - Generates cross-reference stub pages under `books/<source_id>/entities/` namespace
  - Each stub has: term heading, definition excerpt, link to source section, "See also" links
  - Entities index at `entities/index.md` with alphabetical letter navigation
  - Type badges: 📖 lexicon, 📝 inline
  - `entities` CLI command: `pdf-to-wiki entities SOURCE_ID [--force]`
  - Entity slug generation with conflict resolution
  - `find_entity_references()` for detecting term references in text (future: link injection)
  - 28 new tests
- Glossary wired into `build` pipeline:
  - `--glossary` flag on `build` command
  - Auto-enabled for Marker and Docling engines (which preserve bold/italic)
  - Glossary step now step 6/7 in the build pipeline
  - Validation recognizes glossary.md and entity pages as expected output
- PyMuPDF table extraction wiring (Tech debt #6):
  - `config.extract_tables = true` (default): PyMuPDF engine detects tables via `find_tables()`
  - Detected tables converted to Markdown pipe-tables and appended to page text
  - In-place table replacement with block-position tracking is a future enhancement
  - Requires PyMuPDF 1.24+ for `find_tables()` API
- 219 tests passing (28 new entity page tests)

### 2025-04-18 — Glossary extraction, Docling engine, auto-validate

- Glossary extraction module (`src/pdf_to_wiki/repair/extract_glossary.py`):
  - Extracts **Term —** definition entries from lexicon/glossary sections (44 CoD Lexicon entries)
  - Extracts **Term**: inline bold-definition patterns in body text (18 CoD inline entries)
  - Extracts **Field:** structured fields separately (**Effect:**, **Prerequisites:**, etc. — 995 CoD records)
  - Deduplicates by lowercase term, preferring lexicon entries over inline
  - Filters: Marker page-ref artifacts, known false positives, structured field labels, short definitions
  - Emits `books/<source_id>/glossary.md` with alphabetical index and section links
  - `glossary` CLI command: `pdf-to-wiki glossary SOURCE_ID [--force] [--emit]`
- Docling engine integration (`src/pdf_to_wiki/extract/docling_engine.py`):
  - `@register_engine("docling")` following BaseEngine ABC pattern
  - `extract_full_pdf()` and `extract_page_range()` with Docling's `DocumentConverter`
  - Supports Docling's page_range parameter (1-based conversion)
  - `[docling]` optional dependency group in `pyproject.toml` (`docling>=2.0.0`)
  - Graceful ImportError handling when `[docling]` extra not installed
  - ~1-5s/page on CPU (vs. ~30s/page for Marker)
- Auto-validate on build:
  - `build` command now runs `validate_wiki()` automatically after emission
  - `--no-validate` flag to skip post-build validation
  - Resolves technical debt #9 (validate not auto-run)
- 36 new glossary tests (191 total passing)

### 2025-04-18 — Roadmap items: validation, filters, repair fixes, no-TOC fallback, Shadowrun

- `validate` CLI command: post-build validation checking broken Markdown links,
  missing image references, orphan .md files, and unresolved `{{page-ref:N}}` annotations.
  New `src/pdf_to_wiki/emit/validate.py` module with `ValidationReport` dataclass.
- `--dry-run` global CLI flag: reports what would be done without writing files.
  Implemented in `emit_skeleton`, `extract_text`, and `build_section_tree`.
  `dry_run` flag added to `WikiConfig`.
- `--sections` and `--page-range` CLI filters on `build` and `emit-skeleton` commands:
  section_filter matches by section_id, slug, or title substring;
  page_filter restricts to sections overlapping a given page range.
  New `_filter_sections()` helper in `markdown_writer.py`.
- Repair: handle `Wordp. N` pattern (e.g., `Parkourp. 48` → `Parkour p. 48`)
  in `annotate_page_references()` — preprocesses joined game-term + page-ref
  patterns by inserting a space when the term starts with uppercase.
- Repair: HTML `<br>` in Marker pipe tables converted to ` / ` in
  `clean_marker_artifacts()` for broad Markdown compatibility.
- No-TOC PDF fallback: `_synthesize_toc_from_headings()` in `extract_toc.py`
  detects headings via font-size analysis (≥1.3× body text) and creates
  a synthetic TOC when the PDF has no embedded bookmarks. Heading levels
  estimated by relative size (2.0× → L1, 1.5× → L2, 1.3× → L3).
- Image alt text populated from section title: `_rewrite_asset_paths()`
  fills empty alt text `![](.assets/...)` with the section heading.
  Existing non-empty alt text is preserved.
- 155 tests passing (4 new: running header stripping)
- Shadowrun 5E Core Rulebook added to test corpus: 502 pages, 544 sections,
  3-level deep TOC, 2.66M chars, clean validation (0 broken links/images/refs)
- Notable SR observations: ¥/nuyen symbols preserved, SR slang (chummer,
  drek, frag) preserved, no dingbat manifest (no dingbat fonts),
  12 short sections (maps, lifestyle stubs, back matter)

### 2025-04-17 — Marker sub-heading absorption, CoD validation, extraction improvements

- Fix `split_markdown_by_headings()` to absorb unclaimed sub-heading content
  (3-pass approach: match → absorb → assemble). When Marker creates
  sub-headings like "Ranged Weapons Chart" inside "Weapons" that aren't in
  the PDF's TOC, the previous logic lost all table/chart content under those
  sub-headings. Now absorbed by the parent section.
- Impact on CoD Marker build: 785K → 1.63M total chars (+108%),
  475 → 515 sections with ≥50 chars, 13 → 37 sections with pipe tables
- Full Marker build for Chronicles of Darkness validated: 301 pages,
  521 sections, 1875 images, 37 table sections, 1.63M chars
- Mid-page section extraction: font-size-based heading detection via
  `find_heading_position()` (≥1.3× body text), `extract_page_text_structured()`
  with `skip_before=(block_idx, line_idx)` for two-column PDFs
- Single-root TOC unwrapping: `_unwrap_single_root()` promotes children
  when one root matches source_id; `_dedup_slug()` disambiguates
- Dingbat remapping via PyMuPDF font manifest: `extract_dingbat_manifest()`
  scans PDF fonts, `remap_dingbat_bullets()` uses manifest when available
- Marker page-link unwrapping in `clean_marker_artifacts()`: strips
  `[(p.21)](#page-21-0)` before page-ref annotation
- Assets relocated to `books/<source_id>/.assets/` (hidden directory)
- Portable source_pdf frontmatter: `filename.pdf (sha256:hash)`
- Parent section content clipping: pages before first child only
- 130 tests passing (4 new for split_markdown_by_headings)

### 2025-04-16 — Image extraction and preservation

- Extract images from PDF pages using PyMuPDF (94 unique images, 86MB)
- Save images as PNG to `books/<source_id>/.assets/` hidden directory
- Rewrite Marker image references (![_page_N_Picture_X.jpeg]) to
  note-relative paths (../../.assets/page_N_picture_X.png)
- Deduplicate images by content hash across pages
- Fallback matching for Marker page indices that don't align with PyMuPDF
- Add MarkerEngine.extract_full_pdf_with_images() for future use
- Add pdf_images.py module for image extraction and reference rewriting
- Add _rewrite_asset_paths() to markdown_writer for note-relative paths
- 40/40 image references resolved in Storypath book output

### 2025-04-15 — Tables, Markdown links, heading deduplication

- Switch from Obsidian `[[wiki-links]]` to standard `[Title](relative/path.md)` Markdown
  relative links for broad compatibility (GitHub, GitLab, VS Code, commonmark)
- Add `relative_markdown_link()` utility for computing relative paths between notes
- Marker heading split: merge consecutive same-title headings (fixes table sections)
  where Marker emits `# Title` above a table then `# Title` above body text
- Enhance `_deduplicate_heading()` to strip ALL headings matching section title,
  not just the first (handles PDFs with same heading above table and body text)
- Clean Marker page-anchor spans (`<span id="page-N-M"></span>`) from output
- Add `clean_marker_artifacts()` to repair pipeline
- 115 tests passing

### 2025-04-14 — Milestone 4: Multi-PDF wiki ingestion + Milestone 3 completion

- Rewired section path generation to nest chapters under `books/<source_id>/`
- Wiki-links now include source_id namespace for cross-book linking
- Added `build-all` CLI command for batch processing all registered PDFs
- Added global wiki index (`books/index.md`) with book listing and chapter counts
- Added per-book index note with chapter links
- Page reference rewriting resolves across multiple section trees (cross-book)
- Dingbats font mapping: FantasyRPGDings `Y` → `•`, ZapfDingbats, Symbol
- Bullet normalizer preserves TTRPG dot ratings: `••` → `- •`, `•••` → `- ••`
- Expanded OCR word-break repair: forward, element, character, characters
- 112 tests passing

### 2025-04-13 — Milestone 3: Repair and normalization

- Deterministic repair pipeline: OCR word-breaks, bullets, whitespace, page refs
- OCR word-break repair with suffix heuristic and English word pairs
- Page reference annotation and wiki-link rewriting
- Exclusion list for false positives ("much less" preserved)
- Duplicate heading deduplication (Marker heading vs emitted H1)
- `repair` CLI command
- 108 → 112 tests passing

### 2025-04-13 — Milestone 2: Pluggable extraction engines

- Added `pdf_to_wiki.extract` module with `BaseEngine` ABC and engine registry
- Implemented `PyMuPDFEngine` (deterministic, no ML models)
- Implemented `MarkerEngine` (ML-powered, high-quality Markdown output)
- Default engine changed from pymupdf to marker
- Full-PDF Marker conversion with caching (`marker_full_md.md` artifact)
- Heading-based section splitting from Marker's Markdown output
- Config `extract.engine` setting + CLI `--engine` flag
- Text cleaning pipeline: soft-hyphen, hard-hyphen, paragraph assembly, header/footer
- 85 tests passing

### 2025-01-XX — Milestone 1 complete + text extraction

- Initial project skeleton with pyproject.toml and package layout
- Implemented PDF registration, fingerprinting, inspection
- Implemented TOC extraction via PyMuPDF
- Implemented page-label extraction via pypdf
- Built canonical section tree from TOC + page labels
- Implemented Obsidian Markdown skeleton emission with YAML frontmatter
- Implemented SQLite cache/provenance store and filesystem artifacts
- Added text extraction via PyMuPDF
- Markdown notes populated with extracted text content
- 69 tests passing initially