# Roadmap

Build a pipeline that ingests pen-and-paper rulebook PDFs and produces a structured Obsidian-compatible Markdown wiki, preserving full traceability from generated Markdown back to source PDF pages.

---

## Current Status

**Milestone 5 in progress.** The pipeline processes full rulebook PDFs through TOC extraction, section tree construction, text extraction (Marker or PyMuPDF), repair/normalization, and Markdown emission. Tables are preserved via Marker's native Markdown pipe-table output (37 sections with tables in CoD build). Multiple PDFs can be ingested into a shared wiki with proper namespacing. Internal links use standard Markdown relative links (`[Title](../path/to/section.md)`) for broad compatibility. Dingbats font characters (e.g., FantasyRPGDings `Y` → `•`) are remapped via per-PDF font manifest. TTRPG dot ratings (`•`, `••`, `•••`) are preserved. Marker sub-heading absorption ensures tables under unTOC'd headings are captured. Marker page-anchor spans and page-links are stripped. Mid-page section extraction uses font-size-based heading detection.

**Tested on two large rulebooks:**
- **Storypath Ultra Core Manual** (257 pages, 450 sections, 9 tables)
- **Chronicles of Darkness** (301 pages, 521 sections, 37 table sections, 1.63M chars)

**130 tests passing.**

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
- [ ] OCR fallback for problematic pages (optional)
- [ ] LLM-assisted structural disambiguation (cached, optional)

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
- [ ] Configurable output structure (flat vs. nested per book)

### Milestone 5 — Cross-book linking and semantic enrichment 🔜

- [x] Intra-book reference rewriting (page → section → Markdown relative link)
- [x] Cross-book page reference resolution (all_trees parameter)
- [x] Standard Markdown relative links (not Obsidian wiki-links) for broad compatibility
- [x] Table preservation via Marker's native Markdown pipe-table output
- [x] Sub-heading absorption for table content (e.g., Weapons → Ranged/Melee Charts)
- [x] Duplicate heading merge in Marker's section splitting
- [x] Image extraction from PDF and saving to `books/<source_id>/.assets/` hidden directory
- [x] Image reference rewriting (Marker refs → note-relative paths, fallback matching, dedup by content hash)
- [x] Marker artifact cleanup (page-anchor spans and page-links stripped)
- [ ] Aliases and glossary extraction (game-specific terms auto-detected)
- [ ] Entity pages (spells, conditions, skills) as auto-generated stubs
- [ ] LLM-assisted enrichment (cached, optional)

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
- [x] 130 tests passing

### Next

- [ ] Handle PDFs without embedded TOCs (fallback mode using page ranges)
- [ ] Add --dry-run mode and --sections/--page-range CLI filters
- [ ] Alias/glossary extraction from bold/italic game terms in body text
- [ ] Entity page generation (auto-stubs for spells, conditions, skills)
- [ ] Docling integration as alternative to Marker (faster, different tradeoffs)
- [ ] Design extraction artifact schema (structured, not just raw text)
- [ ] Repair pipeline: handle `Wordp. N` pattern (no space before `p.`)
- [ ] HTML `<br>` tag pass-through in Marker table output (convert to `<br>` or `\n`)
- [ ] Build-time validation: broken link checker, orphan file detection
- [ ] Image alt text from context (currently `![](.assets/...)` — add descriptive alt)

### Deferred / Later

- [ ] OCR fallback via OCRmyPDF
- [ ] Font/encoding diagnostics beyond known dingbats fonts
- [ ] Heading repair (extractor vs TOC disagreement)
- [ ] Configurable split depth for note generation
- [ ] Configurable output structure (flat vs. nested per book)
- [ ] Section anchors for reference rewriting
- [ ] Obsidian search index generation
- [ ] LLM-assisted structural disambiguation and enrichment (cached, optional)

---

## Open Questions

1. **Marker vs Docling**: Marker is ~30s/page on CPU (6.5h for CoD 301 pages). Docling may be faster. Should we add Docling as another engine option?
2. **Page-label robustness**: Some PDFs have no /PageLabels at all. Should we attempt to detect Roman-numeral front matter heuristically?
3. **LLM cache eviction policy**: When should cached LLM responses be invalidated? Current design only invalidates on config hash change.
4. **Entity extraction approach**: Should we detect game terms via bold/italic patterns, or use an LLM to identify entities? Bold/italic is fast and deterministic; LLM gives richer results but is slow and non-deterministic.
5. **PyMuPDF table extraction**: `page.find_tables()` can detect tables but produces split-column artifacts. Marker handles tables natively. Should we wire in PyMuPDF table extraction as fallback for when Marker isn't available?
6. **Sub-heading depth limit**: Should sub-heading absorption stop at a certain heading level difference? Currently absorbs all consecutive unclaimed headings; might over-absorb in edge cases.

---

## Technical Debt

1. **CacheDB connection management**: Currently opens/closes per command. Should use a shared connection pool or context manager in a long-running process.
2. **Marker singleton**: The global `_marker_converter` and `_model_dict` are process-level singletons; not safe for multi-threaded use.
3. **No dry-run mode**: The `--dry-run` flag is not yet implemented.
4. **No `--sections` filter**: Cannot limit processing to specific sections.
5. **Old output cleanup**: ✅ Fixed — `emit-skeleton --force` now removes stale files from previous runs.
6. **table_extract.py not wired**: PyMuPDF table detection module exists but isn't integrated into the extraction pipeline; Marker handles tables natively.
7. **6 sections with <50 chars**: Mostly character entries in fiction chapters (God Machine Chronicle NPCs) where content is under sub-headings in the Marker output. Low priority since these are narrative, not rules content.
8. **~30s/page Marker latency**: CoD build took 6.5h. Consider Docling or GPU acceleration for faster builds.

---

## Change Log

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