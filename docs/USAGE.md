# Usage Guide

## Installation

### As a CLI tool (recommended)

```bash
# Install with uv — PyMuPDF engine only (fast, deterministic, no ML models)
uv tool install pdf-to-wiki

# Include the Marker engine for high-quality ML-powered extraction
uv tool install "pdf-to-wiki[marker]"

# Install from source
git clone https://github.com/your-org/pdf-to-wiki.git
cd pdf-to-wiki
uv tool install .
```

### For development

```bash
git clone https://github.com/your-org/pdf-to-wiki.git
cd pdf-to-wiki

# Sync dependencies (creates .venv automatically)
uv sync --extra dev

# Or include Marker support
uv sync --extra dev --extra marker

# Run CLI via uv
uv run pdf-to-wiki --help
```

### Using pip

```bash
pip install pdf-to-wiki

# Include the Marker engine
pip install "pdf-to-wiki[marker]"
```

## CLI Commands

### `pdf-to-wiki register`

Register a PDF source in the pipeline. This fingerprints the file, extracts basic metadata (title, page count), and persists the source record.

```bash
pdf-to-wiki register path/to/my-rulebook.pdf
```

Options:
- `--force` — Re-register even if already cached

### `pdf-to-wiki inspect`

Display metadata for a previously registered PDF.

```bash
pdf-to-wiki inspect my-rulebook
```

### `pdf-to-wiki toc`

Extract and display the PDF's embedded table of contents (bookmarks/outline).

```bash
pdf-to-wiki toc my-rulebook
```

Options:
- `--force` — Force re-extraction

### `pdf-to-wiki page-labels`

Extract printed page labels from the PDF.

```bash
pdf-to-wiki page-labels my-rulebook
```

Options:
- `--force` — Force re-extraction

### `pdf-to-wiki build-section-tree`

Build the canonical section tree from the cached TOC and page label data.

```bash
pdf-to-wiki build-section-tree my-rulebook
```

Options:
- `--force` — Force rebuild

### `pdf-to-wiki extract`

Extract text content from the PDF for each section's page range.

```bash
# Use Marker (default) — high quality, ML-powered, ~30s/page on CPU
pdf-to-wiki extract my-rulebook

# Use PyMuPDF — fast, deterministic, no ML models
pdf-to-wiki extract my-rulebook --engine pymupdf
```

Options:
- `--force` — Force re-extraction (re-runs full Marker conversion)
- `--engine marker|pymupdf` — Override the configured extraction engine

### Extraction Engines

| Engine | Quality | Speed | Requirements |
|--------|--------|-------|-------------|
| **marker** (default) | High — columns, tables, bold/italic, heading hierarchy | ~30s/page (CPU) | `[marker]` extra + ~2GB ML models |
| **pymupdf** | Medium — column-aware, header/footer removal | ~0.1s/page | Core install (no extras needed) |

Marker output is cached at the full-PDF level. First run converts the entire PDF (~2hrs for 257 pages on CPU). Subsequent runs reuse the cached Markdown and split by headings.

### `pdf-to-wiki emit-skeleton`

Emit Markdown files from the section tree with YAML frontmatter.

```bash
pdf-to-wiki emit-skeleton my-rulebook
```

### `pdf-to-wiki build`

Run the full pipeline: register → toc → page-labels → section-tree → extract → emit.

```bash
# Full pipeline with Marker extraction (default)
pdf-to-wiki build my-rulebook

# Fast pipeline with PyMuPDF extraction
pdf-to-wiki build my-rulebook --engine pymupdf

# Skip extraction entirely (skeleton only)
pdf-to-wiki build my-rulebook --skip-extract
```

Options:
- `--force` — Force re-run all steps
- `--force-step <step>` — Force re-run a specific step
- `--engine marker|pymupdf` — Override extraction engine
- `--skip-extract` — Skip text extraction

## Global Options

- `--config <path>` — Path to a configuration TOML file
- `--output-dir <dir>` — Override output directory
- `--cache-dir <dir>` — Override cache directory

## Configuration

The pipeline reads from `pdf-to-wiki.toml` (or `pdf_to_wiki.toml`).

```toml
[wiki]
output_dir = "./data/outputs/wiki"
books_dir = "books"

[cache]
db_path = "./data/cache/cache.db"
artifact_dir = "./data/artifacts"

[llm]
backend = "ollama"
default_model = "glm-5.1:cloud"
temperature = 0.0

[extract]
engine = "marker"   # "marker" (default) or "pymupdf"

[obsidian]
emit_frontmatter = true
emit_index_notes = true
```

## Intermediate Artifacts

Under `data/artifacts/<source_id>/`:

| File | Content |
|------|---------|
| `pdf_source.json` | PDF metadata |
| `toc.json` | TOC entries |
| `page_labels.json` | Page label mappings |
| `section_tree.json` | Full section tree |
| `marker_full_md.md` | Marker's cached full-PDF Markdown output |
| `extract_text.json` | section_id → extracted text |
| `emit_manifest.json` | section_id → output path |

## Running Tests

```bash
# Using uv (from project root)
uv run pytest tests/ -v

# Or if you've synced the dev environment
uv sync --extra dev
pytest tests/ -v
```

Tests use the PyMuPDF engine (fast, no ML models required).

## Source ID Derivation

Derived from the PDF filename: lowercase, spaces/underscores → hyphens, parentheses/brackets stripped.

Examples:
- `Core Rulebook.pdf` → `core-rulebook`
- `PF2e - Core Rulebook (3rd Printing).pdf` → `pf2e-core-rulebook-3rd-printing`