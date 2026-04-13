# Usage Guide

## Installation

```bash
# Create virtual environment
uv venv
source .venv/bin/activate

# Install the package in editable mode
pip install -e ".[dev]"

# Optional: install marker-pdf for high-quality ML extraction
pip install marker-pdf
```

## CLI Commands

### `rulebook-wiki register`

Register a PDF source in the pipeline. This fingerprints the file, extracts basic metadata (title, page count), and persists the source record.

```bash
rulebook-wiki register path/to/my-rulebook.pdf
```

Options:
- `--force` — Re-register even if already cached

### `rulebook-wiki inspect`

Display metadata for a previously registered PDF.

```bash
rulebook-wiki inspect my-rulebook
```

### `rulebook-wiki toc`

Extract and display the PDF's embedded table of contents (bookmarks/outline).

```bash
rulebook-wiki toc my-rulebook
```

Options:
- `--force` — Force re-extraction

### `rulebook-wiki page-labels`

Extract printed page labels from the PDF.

```bash
rulebook-wiki page-labels my-rulebook
```

Options:
- `--force` — Force re-extraction

### `rulebook-wiki build-section-tree`

Build the canonical section tree from the cached TOC and page label data.

```bash
rulebook-wiki build-section-tree my-rulebook
```

Options:
- `--force` — Force rebuild

### `rulebook-wiki extract`

Extract text content from the PDF for each section's page range.

```bash
# Use Marker (default) — high quality, ML-powered, ~30s/page on CPU
rulebook-wiki extract my-rulebook

# Use PyMuPDF — fast, deterministic, no ML models
rulebook-wiki extract my-rulebook --engine pymupdf
```

Options:
- `--force` — Force re-extraction (re-runs full Marker conversion)
- `--engine marker|pymupdf` — Override the configured extraction engine

### Extraction Engines

| Engine | Quality | Speed | Requirements |
|--------|--------|-------|-------------|
| **marker** (default) | High — columns, tables, bold/italic, heading hierarchy | ~30s/page (CPU) | `marker-pdf` + ~2GB ML models |
| **pymupdf** | Medium — column-aware, header/footer removal | ~0.1s/page | PyMuPDF only |

Marker output is cached at the full-PDF level. First run converts the entire PDF (~2hrs for 257 pages on CPU). Subsequent runs reuse the cached Markdown and split by headings.

### `rulebook-wiki emit-skeleton`

Emit Markdown files from the section tree with YAML frontmatter.

```bash
rulebook-wiki emit-skeleton my-rulebook
```

### `rulebook-wiki build`

Run the full pipeline: register → toc → page-labels → section-tree → extract → emit.

```bash
# Full pipeline with Marker extraction (default)
rulebook-wiki build my-rulebook

# Fast pipeline with PyMuPDF extraction
rulebook-wiki build my-rulebook --engine pymupdf

# Skip extraction entirely (skeleton only)
rulebook-wiki build my-rulebook --skip-extract
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

The pipeline reads from `rulebook-wiki.toml` (or `rulebook_wiki.toml`).

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
pytest tests/ -v
```

Tests use the PyMuPDF engine (fast, no ML models required).

## Source ID Derivation

Derived from the PDF filename: lowercase, spaces/underscores → hyphens, parentheses/brackets stripped.

Examples:
- `Core Rulebook.pdf` → `core-rulebook`
- `PF2e - Core Rulebook (3rd Printing).pdf` → `pf2e-core-rulebook-3rd-printing`