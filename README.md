# Rulebook Wiki Pipeline

Convert pen-and-paper rulebook PDFs into structured Obsidian Markdown wikis.

## Installation

### Using uv (recommended)

```bash
# Install as a CLI tool (PyMuPDF engine only — fast, deterministic)
uv tool install pdf-to-wiki

# Or include the Marker engine for high-quality ML extraction
uv tool install "pdf-to-wiki[marker]"

# Or clone and install from source
git clone https://github.com/your-org/pdf-to-wiki.git
cd pdf-to-wiki
uv tool install .
```

### Using pip

```bash
pip install pdf-to-wiki

# Or include the Marker engine
pip install "pdf-to-wiki[marker]"
```

### For development

```bash
git clone https://github.com/your-org/pdf-to-wiki.git
cd pdf-to-wiki

# Create a virtual environment and install with dev dependencies
uv sync --extra dev

# Or with Marker support too
uv sync --extra dev --extra marker

# The CLI is available via the venv
uv run pdf-to-wiki --help
```

## Quick Start

```bash
# Register a PDF
pdf-to-wiki register path/to/book.pdf

# Inspect registration
pdf-to-wiki inspect book

# Extract and view TOC
pdf-to-wiki toc book

# Build the full pipeline (register → toc → page-labels → section-tree → extract → emit)
pdf-to-wiki build book

# Or run individual steps
pdf-to-wiki page-labels book
pdf-to-wiki build-section-tree book
pdf-to-wiki emit-skeleton book
```

## Configuration

Create `pdf-to-wiki.toml` in your project directory:

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

[obsidian]
emit_frontmatter = true
emit_index_notes = true
```

See [docs/USAGE.md](docs/USAGE.md) for detailed usage and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design documentation.

## Project Status

Milestone 1 is complete: the pipeline can ingest a PDF, extract its TOC and page labels, build a canonical section tree, and emit a deterministic Markdown skeleton with full frontmatter.

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full roadmap.

## License

MIT