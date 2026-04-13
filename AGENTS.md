# AGENTS.md — Guide for LLM Coding Agents

## Project Overview

**Rulebook Wiki Pipeline** converts pen-and-paper rulebook PDFs into structured Obsidian Markdown wikis. The pipeline extracts TOC/outline, page labels, and section metadata from PDFs, builds a canonical section tree, and emits deterministic Markdown files with YAML frontmatter.

**Current milestone (M1):** TOC-driven Markdown skeleton for one PDF. Full text extraction, repair, and LLM enrichment are future milestones.

---

## Before Making Changes

1. **Read `README.md`** for a project summary and quick-start commands.
2. **Read the handoff document** (`handoff.md`) for the full design rationale and long-term architecture.
3. **Read `docs/ARCHITECTURE.md`** to understand the current module layout, data flow, and design constraints.
4. **Read `docs/ROADMAP.md`** to understand what is done, what is in progress, and what is deferred.

Do **not** start coding without this context. The architecture has strong opinions about caching, provenance, deterministic operations, and the role of LLMs.

---

## Architecture Constraints

These are **non-negotiable** unless explicitly reconsidered:

- **The PDF TOC is the source of truth for hierarchy.** Do not infer heading depth from text styling.
- **Markdown is NOT the only source of truth.** The canonical section tree JSON and the SQLite/JSON artifacts are the primary records.
- **Use LLMs only for non-deterministic tasks.** TOC extraction, page counting, slug generation, page-label extraction, and Markdown emission must remain deterministic.
- **LLM backend:** Ollama, default model `glm-5.1:cloud`. Cache all LLM calls aggressively.
- **Cache/provenance is built in from the start.** Every expensive step checks the cache before running and records provenance after.
- **Per-step artifacts on disk.** Intermediate results (TOC, page labels, section tree) are persisted as JSON under the artifact directory.
- **Design for multi-PDF ingestion.** All section IDs are namespaced by `source_id`. Even though M1 handles one PDF, the code must not assume global uniqueness of titles or slugs.
- **Preserve backwards compatibility of persisted artifacts** unless intentionally migrating them. Document all schema changes and migrations in `docs/ROADMAP.md`.

---

## Workflow Conventions

- **Small, reviewable, working increments.** Prefer a correct small change over a large speculative refactor.
- **Keep documentation in sync.** When you change code, update:
  - `docs/ROADMAP.md` (task status, change log)
  - `docs/ARCHITECTURE.md` (if architecture changes)
  - `docs/USAGE.md` (if CLI behavior changes)
  - `AGENTS.md` (if agent-facing conventions change)
- **Update `docs/ROADMAP.md`** when starting and finishing substantial tasks.
- **Run the test suite** before declaring work done: `pytest tests/ -v`
- **Avoid undocumented architectural drift.** If you add a new module, data structure, or CLI command, document it.

---

## Key File Locations

| Path | Purpose |
|------|---------|
| `src/rulebook_wiki/` | Main package |
| `src/rulebook_wiki/cli.py` | CLI commands |
| `src/rulebook_wiki/models.py` | Canonical Pydantic data models |
| `src/rulebook_wiki/config.py` | Configuration loading |
| `src/rulebook_wiki/ingest/` | PDF ingestion (register, TOC, page labels, section tree) |
| `src/rulebook_wiki/emit/` | Markdown/obsidian emission |
| `src/rulebook_wiki/cache/` | SQLite cache, artifact store, step manifests |
| `src/rulebook_wiki/extract/` | Future: extraction engine integration (stub) |
| `src/rulebook_wiki/repair/` | Future: repair and normalization (stub) |
| `src/rulebook_wiki/llm/` | Future: LLM-backed enrichment (stub) |
| `src/rulebook_wiki/index/` | Future: global catalog and link graph (stub) |
| `data/` | Runtime data (cache, artifacts, outputs) |
| `tests/` | Test suite |
| `docs/` | Documentation |

---

## CLI Commands (Current)

```bash
rulebook-wiki register <pdf_path>       # Register a PDF source
rulebook-wiki inspect <source_id>       # Show PDF metadata
rulebook-wiki toc <source_id>           # Extract/display TOC
rulebook-wiki page-labels <source_id>   # Extract/display page labels
rulebook-wiki build-section-tree <source_id>  # Build canonical section tree
rulebook-wiki emit-skeleton <source_id> # Emit Markdown skeleton
rulebook-wiki build <source_id>         # Run full pipeline
```

Common flags: `--force`, `--force-step <step>`, `--config <path>`, `--output-dir <dir>`, `--cache-dir <dir>`

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_section_tree.py -v
```

All tests use `tmp_path` fixtures — no persistent state.

---

## When Adding New Pipeline Steps

1. Add a new module in the appropriate subpackage (`ingest/`, `extract/`, `repair/`, `emit/`, `llm/`).
2. Create a Pydantic model for the step's input/output data in `models.py` if needed.
3. Use `CacheDB` and `ArtifactStore` for caching.
4. Use `StepManifestStore` to track step completion.
5. Add a CLI command in `cli.py`.
6. Write tests in `tests/`.
7. Update `docs/ROADMAP.md` and `docs/ARCHITECTURE.md`.