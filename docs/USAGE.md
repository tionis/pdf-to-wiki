# Usage Guide

## Installation

```bash
# Create virtual environment
uv venv
source .venv/bin/activate

# Install the package in editable mode
pip install -e ".[dev]"
```

## CLI Commands

### `rulebook-wiki register`

Register a PDF source in the pipeline. This fingerprints the file, extracts basic metadata (title, page count), and persists the source record.

```bash
rulebook-wiki register path/to/my-rulebook.pdf
```

Options:
- `--force` — Re-register even if already cached

Output:
```
Registered: my-rulebook
  Title:     My Rulebook
  Pages:     320
  SHA-256:   a1b2c3d4e5f6…
```

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

Output:
```
TOC for my-rulebook: 12 entries

[L1] Chapter 1: Introduction  (page 0)
  [L2] Overview  (page 0)
  [L2] Getting Started  (page 2)
[L1] Chapter 2: Characters  (page 4)
  [L2] Attributes  (page 4)
  [L2] Skills  (page 8)
```

### `rulebook-wiki page-labels`

Extract printed page labels from the PDF. If the PDF has no explicit `/PageLabels` dictionary, falls back to 1-indexed numeric labels.

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

Extract text content from the PDF for each section's page range. Uses PyMuPDF's `page.get_text()` for baseline extraction. Results are cached as JSON artifacts.

```bash
rulebook-wiki extract my-rulebook
```

Options:
- `--force` — Force re-extraction

### `rulebook-wiki emit-skeleton`

Emit Markdown skeleton files from the section tree. Creates directories and `.md` files with YAML frontmatter.

```bash
rulebook-wiki emit-skeleton my-rulebook
```

Options:
- `--force` — Force re-emission
- `--force-step <step>` — Force re-run of a specific pipeline step

### `rulebook-wiki build`

Run the full pipeline: register → toc → page-labels → section-tree → extract → emit-skeleton.

```bash
rulebook-wiki build my-rulebook
```

Options:
- `--force` — Force re-run all steps
- `--force-step <step>` — Force re-run a specific step
- `--skip-extract` — Skip text extraction (emit skeleton only)

## Global Options

These apply to all commands:

- `--config <path>` — Path to a configuration TOML file
- `--output-dir <dir>` — Override output directory for generated wiki
- `--cache-dir <dir>` — Override cache directory (sets both DB and artifact paths)

## Configuration

The pipeline reads configuration from `rulebook-wiki.toml` (or `rulebook_wiki.toml`) in the current directory, or from a path specified via `--config`.

### Full Configuration

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
engine = "marker"
use_llm = false
prefer_ocr = false

[obsidian]
emit_frontmatter = true
emit_index_notes = true
```

### Defaults

All configuration values have sensible defaults. You can run the pipeline without a config file — it will use the default paths under `./data/`.

## Output Structure

After running `rulebook-wiki build my-rulebook`, the output directory looks like:

```
data/outputs/wiki/
└── books/
    └── my-rulebook/
        ├── index.md                        # Book-level index
        ├── chapter-1-introduction/
        │   ├── index.md                    # Chapter 1 (has children → directory)
        │   ├── overview.md                 # Leaf section
        │   └── getting-started.md          # Leaf section
        └── chapter-2-characters.md          # Leaf chapter (no sub-sections)
```

### Frontmatter Example

```yaml
---
source_pdf: my-rulebook.pdf
source_pdf_id: my-rulebook
section_id: my-rulebook/chapter-1-introduction/overview
level: 2
pdf_page_start: 0
pdf_page_end: 1
printed_page_start: '1'
printed_page_end: '2'
parent_section_id: my-rulebook/chapter-1-introduction
aliases: []
tags:
- rulebook
- imported
---

# Overview

> Content extraction not yet populated.
```

## Intermediate Artifacts

The pipeline persists intermediate results under `data/artifacts/<source_id>/`:

| File | Content |
|------|---------|
| `pdf_source.json` | PDF metadata (source_id, path, SHA-256, title, page count) |
| `toc.json` | List of TOC entries (level, title, pdf_page) |
| `page_labels.json` | List of page label mappings (page_index, label) |
| `section_tree.json` | Full section tree with all nodes, page ranges, and output paths |
| `extract_text.json` | Extracted text content per section (section_id → text string)

These artifacts enable:
- **Inspection** — understand what each step produced
- **Partial re-runs** — skip steps whose artifacts are already correct
- **Debugging** — trace issues without re-running the full pipeline

## Caching Behavior

- Running the same command twice **skips unchanged steps** automatically
- Use `--force` to re-run the current step
- Use `--force-step toc` to force re-extraction of the TOC (for example)
- Step manifest status is tracked in SQLite: `pending → running → completed/failed`

## Source ID Derivation

The `source_id` is derived deterministically from the PDF filename:
- Filename stem (without `.pdf`)
- Lowercased
- Spaces and underscores → hyphens
- Parentheses and brackets stripped
- Multiple hyphens collapsed

Examples:
- `Core Rulebook.pdf` → `core-rulebook`
- `PF2e - Core Rulebook (3rd Printing).pdf` → `pf2e-core-rulebook-3rd-printing`

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_integration.py -v

# Run with coverage (if pytest-cov installed)
pytest tests/ -v --cov=rulebook_wiki
```