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

# Only emit specific sections
pdf-to-wiki emit-skeleton my-rulebook --sections "combat,magic"

# Only emit sections in page range 10-50
pdf-to-wiki emit-skeleton my-rulebook --page-range 10-50
```

Options:
- `--force` — Force re-emission
- `--force-step <step>` — Force re-run of a specific step
- `--sections <list>` — Comma-separated section IDs/slugs/titles to include
- `--page-range START-END` — Only process sections within page range

### `pdf-to-wiki build`

Run the full pipeline: register → toc → page-labels → section-tree → extract → emit.

```bash
# Full pipeline with Marker extraction (default)
pdf-to-wiki build my-rulebook

# Fast pipeline with PyMuPDF extraction
pdf-to-wiki build my-rulebook --engine pymupdf

# Skip extraction entirely (skeleton only)
pdf-to-wiki build my-rulebook --skip-extract

# Dry run — print what would be done without writing files
pdf-to-wiki --dry-run build my-rulebook

# Only emit specific sections
pdf-to-wiki build my-rulebook --sections "combat,magic"

# Only process sections in page range 10-50
pdf-to-wiki build my-rulebook --page-range 10-50
```

Options:
- `--force` — Force re-run all steps
- `--force-step <step>` — Force re-run a specific step
- `--engine marker|pymupdf` — Override extraction engine
- `--skip-extract` — Skip text extraction
- `--sections <list>` — Comma-separated section IDs/slugs/titles to include
- `--page-range START-END` — Only process sections within page range

### `pdf-to-wiki validate`

Validate an emitted wiki for issues: broken links, missing images, orphan files, unresolved page references.

```bash
# Validate a specific book
pdf-to-wiki validate my-rulebook

# Validate all books
pdf-to-wiki validate --all
```

Returns exit code 1 if any issues are found. The command reports:
- Broken Markdown links (`[Title](path.md)` where path.md doesn't exist)
- Broken image references (`![](.assets/img.png)` where img doesn't exist)
- Orphan `.md` files not in the emit manifest
- Unresolved `{{page-ref:N}}` annotations left in the text

Validation automatically runs at the end of `build` unless `--no-validate` is specified.

### `pdf-to-wiki glossary`

Extract glossary entries from the text content — game terms and their definitions from lexicon sections and inline bold patterns.

```bash
# Extract and cache glossary entries
pdf-to-wiki glossary my-rulebook

# Also emit glossary.md alongside wiki output
pdf-to-wiki glossary my-rulebook --emit

# Force re-extraction
pdf-to-wiki glossary my-rulebook --force
```

The glossary step is also integrated into `build` with the `--glossary` flag (auto-enabled for Marker/Docling engines):

```bash
pdf-to-wiki build my-rulebook --glossary
```

### `pdf-to-wiki entities`

Generate entity cross-reference stub pages from glossary entries. Each entity page links back to its source definition section.

```bash
pdf-to-wiki entities my-rulebook

# Force regeneration
pdf-to-wiki entities my-rulebook --force
```

Requires `pdf-to-wiki glossary` to have been run first. Generates:
- `books/<source_id>/entities/<slug>.md` — Individual entity stub pages
- `books/<source_id>/entities/index.md` — Alphabetical entity index with letter navigation

### `pdf-to-wiki import-blobforge`

Import a BlobForge conversion and optionally run the full pipeline. This places BlobForge's Marker output into the pdf-to-wiki artifact store, then the pipeline skips the expensive Marker conversion step (using the cached output instead).

The original PDF is still needed for TOC extraction, page-label extraction, and dingbat/image processing — but those are all fast (seconds, not hours).

```bash
# Import from a BlobForge conversion zip, then build:
pdf-to-wiki import-blobforge book.pdf --zip abc123.zip --build

# Import from already-extracted content.md:
pdf-to-wiki import-blobforge book.pdf --markdown content.md

# Import and build with glossary + validation:
pdf-to-wiki import-blobforge book.pdf --zip abc123.zip --build --glossary

# Overwrite existing marker artifact:
pdf-to-wiki import-blobforge book.pdf --zip abc123.zip --force --build
```

Options:
- `--zip <path>` — Path to BlobForge conversion zip (contains content.md, assets/, info.json)
- `--markdown <path>` — Path to already-extracted content.md file
- `--force` — Overwrite existing marker artifact
- `--build` — Automatically run the full pipeline after import
- `--glossary` — Extract glossary and entity pages (auto-enabled for Marker)
- `--no-validate` — Skip post-build validation

### `pdf-to-wiki diagnose`

Diagnose font and encoding issues in a registered PDF. Scans each page for all fonts and character codes, reports unusual characters, symbol/dingbat fonts, and encoding issues.

```bash
# Full diagnostics
pdf-to-wiki diagnose my-rulebook

# Focus on specific pages
pdf-to-wiki diagnose my-rulebook --pages 1-30

# Machine-readable JSON output
pdf-to-wiki diagnose my-rulebook --json
```

Reports:
- Font summary (names, sizes, bold/italic, symbol font detection)
- Unusual character detection (control chars, private-use-area, replacement chars)
- Per-page font usage

### `pdf-to-wiki tables`

Extract structured table data from a built wiki. Parses Markdown pipe tables into JSON or CSV suitable for VTT import, spreadsheet export, or structured queries.

```bash
# JSON output (default)
pdf-to-wiki tables my-rulebook

# CSV output
pdf-to-wiki tables my-rulebook --csv

# Only tables with 3+ rows
pdf-to-wiki tables my-rulebook --min-rows 3

# Only tables from specific sections
pdf-to-wiki tables my-rulebook --section weapons
```

## Global Options

- `--config <path>` — Path to a configuration TOML file
- `--output-dir <dir>` — Override output directory
- `--cache-dir <dir>` — Override cache directory
- `--dry-run` — Print what would be done without writing files
  (works with `build`, `emit-skeleton`, `extract` commands)

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