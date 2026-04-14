# AGENTS.md — Guide for LLM Coding Agents

## Project Overview

**PDF-to-Wiki** converts pen-and-paper rulebook PDFs into structured Markdown wikis. The pipeline extracts TOC/outline, page labels, and section metadata from PDFs, builds a canonical section tree, extracts text content per section, and emits Markdown files with YAML frontmatter.

**Current milestone (M2):** Structured text extraction with pluggable engines (Marker + PyMuPDF).

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
- **Default engine is Marker** (high quality, ML-powered). PyMuPDF is the fast fallback.
- **Use LLMs only for non-deterministic tasks.** TOC extraction, page counting, slug generation, page-label extraction, Markdown emission, and engine dispatch must remain deterministic. Marker's ML inference is considered a "deterministic-ish" extraction step (cached, not LLM-driven).
- **LLM backend:** Ollama, default model `glm-5.1:cloud`. Cache all LLM calls aggressively.
- **Cache/provenance is built in from the start.** Every expensive step checks the cache before running and records provenance after.
- **Per-step artifacts on disk.** Intermediate results (TOC, page labels, section tree, full-PDF Marker markdown) are persisted under the artifact directory.
- **Design for multi-PDF ingestion.** All section IDs are namespaced by `source_id`.
- **Preserve backwards compatibility of persisted artifacts** unless intentionally migrating them.

---

## Workflow Conventions

- **Small, reviewable, working increments.** Prefer a correct small change over a large speculative refactor.
- **Keep documentation in sync.** When you change code, update:
  - `docs/ROADMAP.md` (task status, change log)
  - `docs/ARCHITECTURE.md` (if architecture changes)
  - `docs/USAGE.md` (if CLI behavior changes)
  - `AGENTS.md` (if agent-facing conventions change)
- **Run the test suite** before declaring work done: `pytest tests/ -v`
- **Tests must use `engine="pymupdf"`** — Marker requires ML models and takes minutes per test.

---

## Key File Locations

| Path | Purpose |
|------|---------|
| `src/pdf_to_wiki/` | Main package |
| `src/pdf_to_wiki/cli.py` | CLI commands (Click) |
| `src/pdf_to_wiki/models.py` | Canonical Pydantic data models |
| `src/pdf_to_wiki/config.py` | Configuration loading (TOML) |
| `src/pdf_to_wiki/ingest/` | PDF ingestion (register, TOC, page labels, section tree, extract) |
| `src/pdf_to_wiki/ingest/extract_text.py` | Extraction orchestration (engine dispatch, caching) |
| `src/pdf_to_wiki/extract/` | Extraction engine framework + engine implementations |
| `src/pdf_to_wiki/extract/__init__.py` | `BaseEngine` ABC, `@register_engine`, `get_engine()`, `list_engines()` |
| `src/pdf_to_wiki/extract/marker_engine.py` | Marker engine (ML-powered PDF→Markdown) |
| `src/pdf_to_wiki/extract/pymupdf_engine.py` | PyMuPDF engine (deterministic, no ML) |
| `src/pdf_to_wiki/repair/` | Text cleaning and repair |
| `src/pdf_to_wiki/repair/clean_text.py` | Structured extraction + cleaning (columns, headers/footers, hyphens) |
| `src/pdf_to_wiki/emit/` | Markdown/obsidian emission |
| `src/pdf_to_wiki/cache/` | SQLite cache, artifact store, step manifests |
| `src/pdf_to_wiki/llm/` | Future: LLM-backed enrichment (stub) |
| `data/` | Runtime data (cache, artifacts, outputs) — gitignored |
| `tests/` | Test suite |

---

## CLI Commands (Current)

```bash
pdf-to-wiki register <pdf_path>       # Register a PDF source
pdf-to-wiki inspect <source_id>       # Show PDF metadata
pdf-to-wiki toc <source_id>           # Extract/display TOC
pdf-to-wiki page-labels <source_id>   # Extract/display page labels
pdf-to-wiki build-section-tree <source_id>  # Build canonical section tree
pdf-to-wiki extract <source_id>        # Extract text content (--engine marker|pymupdf)
pdf-to-wiki emit-skeleton <source_id> # Emit Markdown skeleton
pdf-to-wiki build <source_id>         # Run full pipeline
pdf-to-wiki build-all                 # Build all registered PDFs
pdf-to-wiki repair <source_id>        # Re-emit with repair/normalization
```

Common flags: `--force`, `--force-step <step>`, `--engine <name>`, `--skip-extract`, `--config <path>`, `--output-dir <dir>`, `--cache-dir <dir>`

---

## Installation Details

The package uses `uv` for dependency management:

- **Core install**: PyMuPDF engine only (fast, no ML models)
- **`[marker]` extra**: Adds `marker-pdf` for high-quality ML extraction (~2GB models)
- **`[dev]` extra**: Adds `pytest` and test utilities

```bash
# CLI tool install (PyMuPDF only)
uv tool install pdf-to-wiki

# CLI tool install with Marker
uv tool install "pdf-to-wiki[marker]"

# Development
uv sync --extra dev          # PyMuPDF only
uv sync --extra dev --extra marker  # With Marker
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

## Installation & Development

```bash
# Install for development (creates .venv, syncs all deps)
uv sync --extra dev

# Include Marker engine support
uv sync --extra dev --extra marker

# Install as a CLI tool from source
uv tool install .

# Or with Marker support
uv tool install ".[marker]"
```

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