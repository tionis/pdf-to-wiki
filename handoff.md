# Rulebook PDF → Obsidian Wiki Pipeline

## Purpose

Build a pipeline that ingests one or more pen-and-paper rulebook PDFs and produces a structured Markdown wiki suitable for Obsidian.

The immediate milestone is intentionally small:

* ingest **one** PDF
* extract the embedded PDF TOC / outline
* build a sane Markdown tree structure from that TOC
* emit chapter / section Markdown files with stable paths and frontmatter

The long-term goal is broader:

* ingest **multiple** rulebook PDFs into a single wiki
* preserve sane document structure even when PDF extraction is imperfect
* repair or reinterpret page-based references where possible
* allow cross-book linking, shared concepts, and global search / indexing
* use LLM assistance only where needed, with strong caching around expensive operations

---

## Primary Requirements

### Functional requirements

1. Ingest one or more PDFs.
2. Extract the PDF outline / bookmarks / TOC and use it as the primary source of section hierarchy.
3. Produce a Markdown file tree suitable for Obsidian.
4. Preserve traceability from generated Markdown back to source PDF pages.
5. Support later enrichment passes:

   * heading repair
   * list repair
   * OCR fallback
   * reference rewriting
   * cross-document linking
6. Support incremental re-runs without recomputing everything.
7. Support ingesting multiple PDFs into one shared output wiki.
8. Make expensive steps cacheable and resumable.
9. Use **Ollama** for LLM-backed steps when needed, with **`glm-5.1:cloud`** as the default model unless a very small embedded model is explicitly chosen for a tiny local task.

### Non-functional requirements

1. Deterministic outputs where possible.
2. Pipeline should be modular and replaceable:

   * PDF metadata extraction
   * text extraction
   * OCR
   * structural repair
   * LLM enrichment
   * wiki emission
3. Strong observability:

   * logs
   * per-step artifacts
   * cached intermediate files
   * provenance metadata
4. Safe to interrupt and resume.
5. Designed for future multi-book linking.

---

## Recommended High-Level Architecture

Build a **coordinator pipeline**, not a monolithic converter.

The system should treat PDF → wiki as a sequence of stages with persisted intermediate artifacts.

### Stages

1. **Inventory / Inspection**

   * register PDF
   * fingerprint file
   * inspect page count
   * extract TOC / outline
   * extract page labels
   * inspect fonts / encoding issues
   * detect whether OCR is likely needed

2. **Segmentation**

   * convert TOC entries into canonical section ranges
   * define top-level chapters and subsection boundaries
   * persist a section tree independent of Markdown generation

3. **Extraction**

   * run PDF extraction engine on selected page ranges
   * initially, extraction can be minimal or deferred if the milestone is TOC-driven skeleton generation
   * later, extraction should produce structured content, not just raw Markdown

4. **Repair / Normalization**

   * normalize headings against TOC structure
   * normalize broken list bullets and symbols
   * collapse page fragments into section text
   * attach provenance metadata

5. **Emission**

   * write Markdown files into a deterministic tree
   * generate frontmatter
   * generate index files and mapping files
   * preserve stable identifiers for future relinking

6. **Linking / Enrichment**

   * rewrite intra-book references
   * later: link related concepts across books
   * later: LLM-assisted summary / alias / glossary enrichment

---

## Core Design Decision

The **PDF outline / TOC is the source of truth for hierarchy**.

Do **not** rely on the extractor alone to infer heading depth for the whole document. PDF layout inference can be wrong; embedded bookmarks are often more reliable for chapter structure.

The extractor should primarily recover:

* text blocks
* lists
* tables
* images
* reading order
* page-local structure

The coordinator should decide:

* section boundaries
* final heading levels
* file layout
* metadata
* cross-reference handling

---

## Recommended Tooling

### Required

* **Python** as orchestration language
* **PyMuPDF** for TOC / bookmark extraction and page inspection
* **pypdf** for page labels and additional PDF metadata
* **Marker** as the main extraction engine for structured extraction later
* **Ollama** for LLM-backed repair / enrichment
* **SQLite** for cache / manifest / provenance store

### Optional / fallback

* **OCRmyPDF** for scanned PDFs or damaged text layers
* **Docling** as an alternative extractor for benchmarking or fallback
* **pdffonts** for diagnostics when text extraction is garbled

### LLM backend policy

Default backend:

* **Ollama**
* default model: **`glm-5.1:cloud`**

Use LLMs only for steps where deterministic logic is clearly insufficient, for example:

* heading disambiguation when extracted text and TOC disagree
* cross-reference repair with fuzzy context
* section title normalization / alias generation
* cross-book concept linking
* glossary extraction

Do **not** use LLMs for:

* PDF page counting
* TOC extraction
* page label extraction
* cache lookups
* deterministic Markdown emission
* simple list normalization

If a very small embedded model is used, it should only be for a clearly local, low-stakes classification task. The default assumption is still Ollama + `glm-5.1:cloud`.

---

## Project Scope by Milestone

## Milestone 1 — TOC-driven Markdown tree for one PDF

### Goal

Given one PDF, generate a Markdown directory / file tree based purely on the embedded TOC.

### Inputs

* one PDF file

### Outputs

* a directory tree of Markdown files
* one file per chapter / section depending on configured granularity
* frontmatter containing source metadata
* a machine-readable section tree JSON

### Minimum acceptable behavior

* extract TOC
* build section hierarchy
* create Markdown files with headings and placeholder content blocks
* include page range metadata for each section
* produce deterministic paths

### Placeholder content is acceptable

For the first milestone, files may contain:

* title
* TOC-derived metadata
* source page range
* optional placeholder markers for later extraction

Example:

```md
---
source_pdf: core-rulebook.pdf
source_pdf_id: core-rulebook
section_id: core-rulebook/chapter-03/combat/damage
level: 3
pdf_page_start: 128
pdf_page_end: 134
printed_page_start: 117
printed_page_end: 123
---

# Damage

> Content extraction not yet populated.
```

### Deliverables

1. PDF registration / fingerprinting
2. TOC extraction
3. page-label extraction
4. canonical section tree JSON
5. Markdown emitter
6. CLI entrypoint

---

## Milestone 2 — Structured text extraction for one PDF

### Goal

Populate the Markdown files with extracted content while preserving section boundaries from the TOC.

### Requirements

* process PDF by section or chapter page ranges
* store extractor outputs in cache
* prefer structured intermediate output over direct Markdown
* merge extracted content into the existing section tree

### Notes

Marker should be run in a mode that produces structured intermediate artifacts. The coordinator should then map extracted content into TOC-owned sections.

---

## Milestone 3 — Repair and normalization

### Goal

Improve output quality for real rulebooks.

### Requirements

* normalize broken bullets / weird symbols
* detect extractor artifacts
* optionally re-run problematic pages with OCR
* normalize whitespace and paragraph joins
* preserve tables and images where possible

### LLM use

Allowed only for difficult structural ambiguity or semantic cleanup. All LLM outputs must be cached.

---

## Milestone 4 — Multi-PDF wiki ingestion

### Goal

Support many PDFs in one shared wiki.

### Requirements

* namespace PDFs cleanly
* avoid collisions between identical section titles
* support shared concept pages later
* maintain per-source provenance
* support global linking and future deduplication

### Key rule

Per-PDF structure and global wiki structure must be related but not identical.

A source book may remain under its own namespace, while the global wiki can later expose merged concept pages.

---

## Milestone 5 — Cross-book linking and semantic enrichment

### Goal

Create a genuinely useful interconnected rules wiki.

### Possible features

* aliases for rule concepts
* inferred links between similar mechanics across books
* glossary pages
* entity pages for spells, conditions, skills, ancestries, etc.
* backlinks to originating books and sections
* global search index

This stage is where LLM assistance becomes more useful, but only with strong provenance and cache discipline.

---

## Proposed Repository Structure

```text
rulebook-wiki-pipeline/
  pyproject.toml
  README.md
  src/rulebook_wiki/
    cli.py
    config.py
    models.py
    logging.py

    ingest/
      register_pdf.py
      fingerprint.py
      inspect_pdf.py
      extract_toc.py
      extract_page_labels.py
      build_section_tree.py

    extract/
      marker_runner.py
      ocr_runner.py
      extractor_registry.py

    repair/
      heading_repair.py
      list_normalization.py
      reference_rewrite.py
      section_merge.py

    emit/
      markdown_writer.py
      asset_writer.py
      obsidian_paths.py

    llm/
      ollama_client.py
      prompts/
      cache_keys.py
      enrichment.py
      link_inference.py

    cache/
      db.py
      artifact_store.py
      manifests.py

    index/
      provenance.py
      global_catalog.py
      link_graph.py

  data/
    cache/
    artifacts/
    manifests/
    outputs/
```

---

## Canonical Data Model

The system should maintain an internal canonical representation. Markdown is only one rendered view.

### PDF source

```python
class PdfSource:
    source_id: str
    path: str
    sha256: str
    title: str | None
    page_count: int
```

### TOC entry

```python
class TocEntry:
    level: int
    title: str
    pdf_page_start: int
    pdf_page_end: int | None
    printed_page_start: str | None
    printed_page_end: str | None
```

### Section node

```python
class SectionNode:
    section_id: str
    source_id: str
    title: str
    slug: str
    level: int
    parent_id: str | None
    children: list[str]
    pdf_page_start: int
    pdf_page_end: int
    printed_page_start: str | None
    printed_page_end: str | None
    extractor_artifact_path: str | None
    markdown_output_path: str | None
```

### Extracted block

```python
class ExtractedBlock:
    block_id: str
    section_id: str
    kind: str
    text: str | None
    page: int
    bbox: tuple[float, float, float, float] | None
    metadata: dict
```

### Provenance record

```python
class ProvenanceRecord:
    artifact_id: str
    source_id: str
    section_id: str | None
    step: str
    tool: str
    tool_version: str | None
    config_hash: str
    created_at: str
```

---

## Output Layout Strategy

The output must be stable and collision-resistant.

Suggested path pattern:

```text
outputs/wiki/
  books/
    core-rulebook/
      index.md
      chapter-01-introduction.md
      chapter-02-character-creation/
        index.md
        attributes.md
        skills.md
```

### Path rules

1. Stable slug generation.
2. Include numeric ordering prefixes only when needed for deterministic order.
3. Preserve a stable `section_id` independent of path changes if possible.
4. Support future relocation without breaking identity.

### Frontmatter requirements

Every generated note should include:

```yaml
source_pdf: core-rulebook.pdf
source_pdf_id: core-rulebook
section_id: core-rulebook/chapter-02/skills
level: 2
pdf_page_start: 45
pdf_page_end: 53
printed_page_start: 31
printed_page_end: 39
parent_section_id: core-rulebook/chapter-02
aliases: []
tags:
  - rulebook
  - imported
```

---

## Caching Strategy

Caching is a first-class requirement.

### Cacheable operations

1. PDF fingerprinting and metadata extraction
2. TOC extraction
3. page-label extraction
4. extraction engine outputs by page range
5. OCR outputs by page range
6. LLM prompts + responses
7. rendered Markdown per section
8. reference-rewrite results

### Cache keys

Cache keys should incorporate:

* source PDF hash
* step name
* page range or section id
* tool name
* tool version
* normalized configuration hash
* prompt hash for LLM steps
* model identifier for LLM steps

### Requirements

* cache lookup must happen before expensive work
* cache records must include provenance
* cache invalidation should be targeted, not global
* CLI should support `--force` and `--force-step`

### Storage

Use SQLite for manifests / metadata and a filesystem artifact store for large blobs.

Suggested split:

* SQLite for cache index, step records, provenance, config hashes
* filesystem for JSON artifacts, OCR PDFs, extracted images, rendered Markdown intermediates

---

## LLM Usage and Caching Policy

### Backend

Use Ollama.

### Default model

`glm-5.1:cloud`

### Required wrapper behavior

The LLM client must:

* support explicit model selection
* compute prompt hash
* cache responses
* preserve raw prompt / response artifacts
* record temperature and relevant generation settings
* support offline skip / dry-run behavior

### Suggested interface

```python
class LlmRequest:
    task: str
    model: str
    prompt: str
    system: str | None
    temperature: float
    response_format: str | None

class LlmResponse:
    text: str
    model: str
    prompt_hash: str
    cached: bool
    raw: dict | None
```

### Rules

1. Never call the LLM without a cache check.
2. Never let the LLM mutate the source of truth directly.
3. LLM output should produce proposals or enrichments that are then validated and persisted.
4. Prefer structured JSON responses for machine-consumed tasks.

---

## Multi-PDF Ingestion Design

This must be considered from the beginning even if Milestone 1 handles only one PDF.

### Principles

1. A `source_id` namespace must exist for every PDF.
2. Section identities must be namespaced by source.
3. Cross-source linking must be additive and optional.
4. Global concept pages should be a later layer, not the initial storage format.

### Recommended model

Keep two layers:

#### Layer 1: Source-preserving book import

* one tree per PDF
* faithful to the source TOC
* minimal semantic merging

#### Layer 2: Global semantic overlay

* shared entities / concepts / mechanics
* backlinks to sections in one or more PDFs
* optional LLM-assisted aliasing and deduplication

This avoids destructive merging early on.

---

## Reference Rewriting Strategy

Rulebooks often say things like:

* see page 123
* see Chapter 7
* see Damage on page 201

The system should preserve enough mapping data to later rewrite such references.

### Required mapping artifacts

* PDF index page → printed page label
* printed page label → section id
* section id → output path / anchor

### Phases

#### Initial phase

Store references as-is, but keep mapping metadata for later.

#### Later phase

Attempt deterministic rewrites first:

* exact printed page match
* exact TOC title match
* chapter title match

#### Advanced phase

Use LLM only for ambiguous fuzzy reference resolution.

---

## CLI Requirements

The pipeline should be operable from the terminal.

Suggested commands:

```bash
rulebook-wiki register path/to/book.pdf
rulebook-wiki inspect core-rulebook
rulebook-wiki toc core-rulebook
rulebook-wiki emit-skeleton core-rulebook
rulebook-wiki extract core-rulebook
rulebook-wiki repair core-rulebook
rulebook-wiki build core-rulebook
rulebook-wiki build-all
```

### Important flags

```bash
--config path/to/config.toml
--output-dir path/to/wiki
--cache-dir path/to/cache
--force
--force-step extract
--sections chapter-01,chapter-02
--page-range 10-30
--dry-run
```

---

## Configuration

Use a project config file.

Example:

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

---

## Testing Strategy

### Unit tests

* TOC parsing
* section range building
* slug generation
* stable path generation
* cache key generation
* page label mapping

### Golden tests

Use a small sample PDF and snapshot:

* section tree JSON
* generated Markdown tree
* frontmatter

### Integration tests

* single-PDF skeleton build
* rerun without recomputing cached steps
* forced rebuild of one step
* multi-PDF namespace handling

### Manual review targets

* weird bullets
* multi-column layouts
* appendices
* Roman numeral front matter
* missing or partial TOCs

---

## Error Handling and Fallbacks

### Missing TOC

If a PDF has no embedded TOC:

* emit a warning
* fall back to extractor-inferred headings later
* for Milestone 1, allow a page-range-only flat import mode

### Broken page labels

If printed page labels are unavailable:

* use PDF page indices
* preserve this fact explicitly in metadata

### Garbled bullets / symbols

* mark the affected pages
* prefer OCR fallback or later normalization
* do not silently drop content

### Extraction failure

* persist failure metadata
* continue with other sections where possible
* leave placeholder content rather than aborting the whole build

---

## Implementation Order

### Phase 1

Implement only the smallest vertical slice:

1. register PDF
2. extract TOC
3. extract page labels
4. build canonical section tree
5. emit Markdown skeleton

### Phase 2

Add cache manifests and deterministic rerun behavior.

### Phase 3

Add extraction integration.

### Phase 4

Add repair / normalization.

### Phase 5

Add multi-PDF import registry and global catalog.

### Phase 6

Add LLM-assisted enrichment and cross-book linking.

---

## Explicit Guidance to the Implementation Agent

1. Do not start by solving full PDF text extraction quality.
2. Start by building the canonical source / TOC / section tree pipeline.
3. Treat the section tree as the backbone of the entire system.
4. Keep every expensive step cacheable and resumable.
5. Assume there will be multiple PDFs later even if the first milestone only uses one.
6. Assume LLM calls are expensive and must be cached aggressively.
7. Use **Ollama** and default to **`glm-5.1:cloud`** for LLM-backed tasks.
8. Preserve provenance everywhere.
9. Never make Markdown the only source of truth.
10. Favor structured intermediate artifacts over direct text transformations.

---

## Definition of Done for Milestone 1

Milestone 1 is done when:

1. A user can point the tool at one PDF.
2. The tool extracts the embedded TOC and page labels.
3. The tool emits a stable Markdown tree matching the TOC hierarchy.
4. Every generated Markdown file contains frontmatter with source and page metadata.
5. The pipeline can be rerun without recomputing unchanged steps.
6. The internal section tree JSON is persisted for later stages.

---

## Stretch Goals After Milestone 1

* configurable split depth for note generation
* per-section placeholder extraction summaries
* global top-level wiki index page
* image extraction
* source PDF backlinks in notes
* section anchors for later reference rewriting
* concept registry for future cross-book merging

---

## Final Summary

The correct first implementation is **not** “convert the PDF to Markdown.”

It is:

1. identify the PDF as a source
2. extract and normalize its TOC / page metadata
3. build a canonical section tree
4. emit a deterministic Obsidian-friendly Markdown skeleton
5. add extraction, repair, caching, and enrichment on top of that backbone

This preserves flexibility, supports multiple books later, and keeps LLM use constrained, explainable, and cacheable.
