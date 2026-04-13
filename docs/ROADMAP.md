# Roadmap

## Goal

Build a pipeline that ingests pen-and-paper rulebook PDFs and produces a structured Obsidian Markdown wiki, preserving full traceability from generated Markdown back to source PDF pages.

---

## Current Status

**Milestone 1 complete.** The pipeline can ingest one PDF, extract its embedded TOC and page labels, build a canonical section tree, and emit a deterministic Markdown skeleton with full frontmatter. Reruns skip unchanged steps via the caching system.

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
- [x] Test suite (60 tests passing)
- [x] Project documentation (README, ARCHITECTURE, USAGE, AGENTS, ROADMAP)

### Milestone 2 — Structured text extraction for one PDF 🔜

- [ ] Integrate Marker (or alternative) extractor
- [ ] Extract content per section page ranges
- [ ] Store extractor outputs as structured artifacts
- [ ] Merge extracted content into section tree nodes
- [ ] CLI: `rulebook-wiki extract <source_id>`

### Milestone 3 — Repair and normalization 🔜

- [ ] Normalize broken list bullets and symbols
- [ ] Detect and mark extractor artifacts
- [ ] Optional OCR fallback for problematic pages
- [ ] Normalize whitespace and paragraph joins
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
- [x] Canonical data models (PdfSource, TocEntry, PageLabel, SectionNode, SectionTree, ProvenanceRecord, StepManifest)
- [x] SHA-256 fingerprinting and source_id derivation
- [x] PDF registration with metadata extraction
- [x] TOC extraction via PyMuPDF with caching
- [x] Page-label extraction via pypdf with Roman-numeral support
- [x] Section tree construction from TOC + page labels
- [x] Deterministic slug generation
- [x] Obsidian Markdown skeleton emission with YAML frontmatter
- [x] Book-level index notes with Obsidian wiki-links
- [x] SQLite cache DB with schema v1
- [x] Filesystem artifact store
- [x] Step manifest tracking (running → completed/failed)
- [x] --force and --force-step CLI options
- [x] `build` command for full pipeline execution
- [x] Test suite: fingerprint, register, TOC, page labels, section tree, emission, cache, integration

### Next

- [ ] Investigate Marker integration for text extraction
- [ ] Design extraction artifact schema (structured, not just raw Markdown)
- [ ] Implement section-scoped extraction runner
- [ ] Add content population to emitted Markdown files

### Deferred / Later

- [ ] OCR fallback via OCRmyPDF
- [ ] Font/encoding diagnostics
- [ ] Heading repair (extractor vs TOC disagreement)
- [ ] List normalization
- [ ] Reference rewriting (page → section → wiki-link)
- [ ] Cross-book concept registry
- [ ] Global concept overlay layer
- [ ] Shared entity pages
- [ ] Image extraction
- [ ] Configurable split depth for note generation
- [ ] Section anchors for reference rewriting
- [ ] Concept registry for cross-book merging

---

## Open Questions

1. **Marker integration depth**: Should Marker be a hard dependency or an optional extra? How do we handle Marker's own caching?
2. **Section-level vs page-level extraction granularity**: Should extraction artifacts be per-section or per-page-range?
3. **Page-label robustness**: Some PDFs have no /PageLabels at all. Should we attempt to detect Roman-numeral front matter heuristically?
4. **Collision handling for multi-PDF**: When two books have sections with identical slugs, how do we disambiguate? Namespace prefix is the current plan.
5. **LLM cache eviction policy**: When should cached LLM responses be invalidated? Current design only invalidates on config hash change.

---

## Technical Debt

1. **CacheDB connection management**: Currently opens/closes per command. Should use a shared connection pool or context manager in a long-running process.
2. **pypdf page-label extraction**: The `_header` attribute access is fragile. Need a more robust way to access /PageLabels from pypdf's API.
3. **Section tree stack algorithm**: The current implementation works but could benefit from a cleaner traversal with explicit parent tracking.
4. **No dry-run mode**: The `--dry-run` flag is mentioned in the handoff but not yet implemented.
5. **No `--sections` filter**: Cannot limit processing to specific sections.
6. **No `--page-range` filter**: Cannot limit processing to a page range.

---

## Change Log

### 2025-01-XX — Milestone 1 complete

- Initial project skeleton with pyproject.toml and package layout
- Implemented PDF registration, fingerprinting, inspection
- Implemented TOC extraction via PyMuPDF
- Implemented page-label extraction via pypdf
- Built canonical section tree from TOC + page labels
- Implemented Obsidian Markdown skeleton emission with YAML frontmatter
- Implemented SQLite cache/provenance store and filesystem artifacts
- Implemented step manifest tracking with --force support
- Full CLI with register, inspect, toc, page-labels, build-section-tree, emit-skeleton, build
- 60 tests passing across all modules
- Documentation: README, ARCHITECTURE, USAGE, AGENTS, ROADMAP