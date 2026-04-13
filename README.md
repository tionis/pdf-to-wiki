# Rulebook Wiki Pipeline

Convert pen-and-paper rulebook PDFs into structured Obsidian Markdown wikis.

## Quick Start

```bash
pip install -e .

# Register a PDF
rulebook-wiki register path/to/book.pdf

# Inspect registration
rulebook-wiki inspect book

# Extract and view TOC
rulebook-wiki toc book

# Build the full pipeline (register → toc → page-labels → section-tree → emit-skeleton)
rulebook-wiki build book

# Or run individual steps
rulebook-wiki page-labels book
rulebook-wiki build-section-tree book
rulebook-wiki emit-skeleton book
```

## Configuration

Create `rulebook-wiki.toml` in your project directory:

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