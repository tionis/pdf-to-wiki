# Roadmap

## Goal

Build a pipeline that ingests pen-and-paper rulebook PDFs and produces a structured Obsidian Markdown wiki, preserving full traceability from generated Markdown back to source PDF pages.

---

## Current Status

**Milestone 2 in progress.** The pipeline supports pluggable extraction engines: Marker (ML-powered, high-quality) and PyMuPDF (deterministic, no models). Marker is the default engine, producing properly formatted Markdown with columns, tables, bold/italic, and heading hierarchy. PyMuPDF is available as a fast fallback. Full-PDF Marker output is cached for reuse.

Tested on Storypath Ultra Core Manual (257 pages, 450 TOC entries).

---

## Milestones

### Milestone 1 — TOC-driven Markdown tree for one PDF ✅

- [x] PDF registration and fingerprinting
- [x] TOC extraction via PyMuPDF
- [x] Page-label extraction via pypdf
- [x] Canonical section tree data structures and persistence
- [x] Deterministic Obsidian Markdown skeleton emission
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
- [x] CLI `--engine` flag to override per-run (`rulebook-wiki extract SRC --engine pymupdf`)
- [x] Full-PDF Marker conversion with single-pass caching (`marker_full_md.md` artifact)
- [x] Heading-based section splitting from Marker's Markdown output
- [x] Fallback to PyMuPDF for sections without heading matches
- [x] Text cleaning pipeline: soft-hyphen removal, hard-hyphen rejoin, paragraph assembly, page-number stripping, header/footer detection and removal
- [x] 85 tests passing
- [x] Provenance tracking records engine name and version

### Milestone 3 — Repair and normalization ✅

- [x] OCR word-break repair (suffix-based heuristic + specific English word pairs)
- [x] Bullet list normalization (•, ◦, ▪ → Markdown `-`)
- [x] Whitespace normalization (collapse excessive blank lines, strip trailing)
- [x] Page reference annotation (`p. 43` → `{{page-ref:43}}`)
- [x] Duplicate heading deduplication (Marker heading vs emitted H1)
- [x] `repair` CLI command (re-emits with repair applied)
- [x] 103 tests passing
- [x] Exclusion list for false-positive preventions ("much less" not joined)
- [ ] Actual wiki-link rewriting (`{{page-ref:43}}` → `[[damage]]`)
- [ ] OCR fallback for problematic pages (optional)
- [ ] Preserve tables and images where possible
- [ ] LLM-assisted structural disambiguation (cached, optional)

### Milestone 4 — Multi-PDF wiki ingestion 🔜

- [ ] Support multiple PDFs in one shared wiki
- [ ] Namespace PDFs cleanly (per-source trees)
- [ ] Collision avoidance for identical section titles
- [ ] Global top-level wiki index
- [ ] Per-source provenance preservation
- [ ] CLI: `rulebook-wiki build-all`

### Milestone 5 — Cross-book linking and semantic enrichment 🔜

- [ ] Intra-book reference rewriting (page → section → wiki-link)
- [ ] Cross-book concept linking
- [ ] Aliases and glossary extraction
- [ ] Entity pages (spells, conditions, skills)
- [ ] Global search index
- [ ] LLM-assisted enrichment (cached, optional)

---

## Tasks

### Completed

- [x] Project skeleton: pyproject.toml, package structure, CLI entrypoint
- [x] Config loading from TOML with defaults
- [x] Canonical data models
- [x] SHA-256 fingerprinting and source_id derivation
- [x] PDF registration with metadata extraction
- [x] TOC extraction via PyMuPDF with caching
- [x] Page-label extraction via pypdf
- [x] Section tree construction from TOC + page labels
- [x] Deterministic slug generation
- [x] Obsidian Markdown skeleton emission with YAML frontmatter
- [x] Book-level index notes with Obsidian wiki-links
- [x] SQLite cache/provenance store and filesystem artifacts
- [x] Step manifest tracking (running → completed/failed)
- [x] --force and --force-step CLI options
- [x] `build` command for full pipeline execution
- [x] Text extraction via PyMuPDF (baseline)
- [x] Structured text cleaning (soft-hyphen, hard-hyphen, headers/footers, paragraphs)
- [x] Pluggable extraction engine (Marker + PyMuPDF)
- [x] Full-PDF Marker conversion with caching
- [x] Heading-based Markdown section splitting

### Next

- [ ] Improve heading-based section splitting accuracy (fuzzy matching, page-range hints)
- [ ] Design extraction artifact schema (structured, not just raw text)
- [ ] Implement section-scoped extraction improvements
- [ ] Handle PDFs without embedded TOCs (fallback mode)
- [ ] Add --dry-run mode and --sections/--page-range filters
- [ ] Docling integration as alternative to Marker (faster, different tradeoffs)

### Deferred / Later

- [ ] OCR fallback via OCRmyPDF
- [ ] Font/encoding diagnostics
- [ ] Heading repair (extractor vs TOC disagreement)
- [ ] List normalization
- [ ] Reference rewriting (page → section → wiki-link)
- [ ] Image extraction from Marker output
- [ ] Configurable split depth for note generation
- [ ] Section anchors for reference rewriting

---

## Open Questions

1. **Marker vs Docling**: Marker is ~30s/page on CPU. Docling may be faster. Should we add Docling as another engine option?
2. **Section splitting accuracy**: Heading-based splitting from Marker output works for major headings but misses smaller subsections. Should we use page-range heuristics as a secondary signal?
3. **Page-label robustness**: Some PDFs have no /PageLabels at all. Should we attempt to detect Roman-numeral front matter heuristically?
4. **Collision handling for multi-PDF**: When two books have sections with identical slugs, how do we disambiguate? Namespace prefix is the current plan.
5. **LLM cache eviction policy**: When should cached LLM responses be invalidated? Current design only invalidates on config hash change.

---

## Technical Debt

1. **CacheDB connection management**: Currently opens/closes per command. Should use a shared connection pool or context manager in a long-running process.
2. **Section splitting**: Current heading-based splitting from Marker output has 0% match rate for some PDFs; needs page-range aware fallback
3. **Marker singleton**: The global `_marker_converter` and `_model_dict` are process-level singletons; not safe for multi-threaded use
4. **No dry-run mode**: The `--dry-run` flag is not yet implemented
5. **No `--sections` filter**: Cannot limit processing to specific sections

---

## Change Log

### 2025-04-13 — Milestone 2: Pluggable extraction engines

- Added `rulebook_wiki.extract` module with `BaseEngine` ABC and engine registry
- Implemented `PyMuPDFEngine` (deterministic, no ML models)
- Implemented `MarkerEngine` (ML-powered, high-quality Markdown output)
- Default engine changed from pymupdf to marker
- Full-PDF Marker conversion with caching (`marker_full_md.md` artifact)
- Heading-based section splitting from Marker's Markdown output
- Config `extract.engine` setting + CLI `--engine` flag
- Text cleaning pipeline: soft-hyphen, hard-hyphen, paragraph assembly, header/footer
- Updated extract command to dispatch through engine registry
- Updated build command with --engine flag
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