"""CLI entrypoint for the pdf-to-wiki pipeline."""

from __future__ import annotations

import click

from pdf_to_wiki.config import load_config


@click.group()
@click.option("--config", "config_path", default=None, help="Path to config TOML file")
@click.option("--output-dir", default=None, help="Override output directory")
@click.option("--cache-dir", default=None, help="Override cache directory")
@click.option("--dry-run", is_flag=True, help="Print what would be done without writing files")
@click.pass_context
def main(ctx: click.Context, config_path: str | None, output_dir: str | None, cache_dir: str | None, dry_run: bool) -> None:
    """PDF-to-Wiki — convert PDF rulebooks into structured Markdown wikis."""
    ctx.ensure_object(dict)
    cfg = load_config(config_path)
    if output_dir is not None:
        cfg.output_dir = output_dir
    if cache_dir is not None:
        cfg.cache_db_path = f"{cache_dir}/cache.db"
        cfg.artifact_dir = f"{cache_dir}/artifacts"
    if dry_run:
        cfg.dry_run = True
    ctx.obj["config"] = cfg


@main.command()
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Force re-registration even if already cached")
@click.pass_context
def register(ctx: click.Context, pdf_path: str, force: bool) -> None:
    """Register a PDF source in the pipeline."""
    from pdf_to_wiki.ingest.register_pdf import register_pdf

    cfg = ctx.obj["config"]
    source = register_pdf(pdf_path, cfg, force=force)
    click.echo(f"Registered: {source.source_id}")
    click.echo(f"  Title:     {source.title or '(none)'}")
    click.echo(f"  Pages:     {source.page_count}")
    click.echo(f"  SHA-256:   {source.sha256[:16]}…")


@main.command()
@click.argument("source_id")
@click.pass_context
def inspect(ctx: click.Context, source_id: str) -> None:
    """Inspect a registered PDF source."""
    from pdf_to_wiki.ingest.inspect_pdf import inspect_pdf

    cfg = ctx.obj["config"]
    source = inspect_pdf(source_id, cfg)
    if source is None:
        click.echo(f"No registered PDF with source_id={source_id!r}", err=True)
        raise SystemExit(1)
    click.echo(f"Source ID:   {source.source_id}")
    click.echo(f"  Path:      {source.path}")
    click.echo(f"  Title:     {source.title or '(none)'}")
    click.echo(f"  Pages:     {source.page_count}")
    click.echo(f"  SHA-256:   {source.sha256[:16]}…")


@main.command()
@click.argument("source_id")
@click.option("--force", is_flag=True, help="Force re-extraction")
@click.pass_context
def toc(ctx: click.Context, source_id: str, force: bool) -> None:
    """Extract the PDF's embedded table of contents."""
    from pdf_to_wiki.ingest.extract_toc import extract_toc

    cfg = ctx.obj["config"]
    entries = extract_toc(source_id, cfg, force=force)
    click.echo(f"TOC for {source_id}: {len(entries)} entries")
    click.echo()
    for entry in entries:
        indent = "  " * (entry.level - 1)
        click.echo(f"{indent}[L{entry.level}] {entry.title}  (page {entry.pdf_page})")


@main.command(name="page-labels")
@click.argument("source_id")
@click.option("--force", is_flag=True, help="Force re-extraction")
@click.pass_context
def page_labels(ctx: click.Context, source_id: str, force: bool) -> None:
    """Extract printed page labels from the PDF."""
    from pdf_to_wiki.ingest.extract_page_labels import extract_page_labels

    cfg = ctx.obj["config"]
    labels = extract_page_labels(source_id, cfg, force=force)
    click.echo(f"Page labels for {source_id}: {len(labels)} entries")
    click.echo()
    for pl in labels[:20]:
        click.echo(f"  Page {pl.page_index}: \"{pl.label}\"")
    if len(labels) > 20:
        click.echo(f"  ... and {len(labels) - 20} more")


@main.command(name="build-section-tree")
@click.argument("source_id")
@click.option("--force", is_flag=True, help="Force rebuild")
@click.pass_context
def build_section_tree(ctx: click.Context, source_id: str, force: bool) -> None:
    """Build the canonical section tree from TOC and page labels."""
    from pdf_to_wiki.ingest.build_section_tree import build_section_tree

    cfg = ctx.obj["config"]
    tree = build_section_tree(source_id, cfg, force=force)
    click.echo(f"Section tree for {source_id}: {len(tree.nodes)} nodes, {len(tree.root_ids)} roots")
    click.echo()
    for rid in tree.root_ids:
        node = tree.nodes[rid]
        click.echo(f"  {node.title} [{node.section_id}] (pages {node.pdf_page_start}-{node.pdf_page_end})")


@main.command(name="extract")
@click.argument("source_id")
@click.option("--force", is_flag=True, help="Force re-extraction")
@click.option("--engine", default=None, help="Extraction engine: marker (default) or pymupdf")
@click.pass_context
def extract(ctx: click.Context, source_id: str, force: bool, engine: str | None) -> None:
    """Extract text content from the PDF for each section."""
    from pdf_to_wiki.ingest.extract_text import extract_text

    cfg = ctx.obj["config"]
    result = extract_text(source_id, cfg, force=force, engine=engine)
    total_chars = sum(len(t) for t in result.values())
    non_empty = sum(1 for t in result.values() if t.strip())
    engine_used = engine or cfg.extract_engine
    click.echo(f"Extracted text for {source_id} (engine: {engine_used}):")
    click.echo(f"  Sections with content: {non_empty}/{len(result)}")
    click.echo(f"  Total characters: {total_chars:,}")


@main.command(name="emit-skeleton")
@click.argument("source_id")
@click.option("--force", is_flag=True, help="Force re-emission")
@click.option("--force-step", default=None, help="Force re-run of a specific step")
@click.option("--sections", default=None, help="Comma-separated section IDs or slugs to process")
@click.option("--page-range", default=None, help="Only process sections within page range (e.g., '10-50')")
@click.pass_context
def emit_skeleton(ctx: click.Context, source_id: str, force: bool, force_step: str | None, sections: str | None, page_range: str | None) -> None:
    """Emit Markdown skeleton files from the section tree."""
    from pdf_to_wiki.emit.markdown_writer import emit_skeleton

    cfg = ctx.obj["config"]
    section_filter = [s.strip() for s in sections.split(",")] if sections else None
    page_filter = _parse_page_range(page_range) if page_range else None
    manifest = emit_skeleton(source_id, cfg, force=force, force_step=force_step, section_filter=section_filter, page_filter=page_filter)
    click.echo(f"Emitted {len(manifest)} Markdown notes for {source_id}")
    click.echo()
    for sid, path in sorted(manifest.items()):
        click.echo(f"  {sid} → {path}")


@main.command(name="build-all")
@click.option("--force", is_flag=True, help="Force re-run all steps for all PDFs")
@click.option("--engine", default=None, help="Extraction engine: marker (default) or pymupdf")
@click.pass_context
def build_all(ctx: click.Context, force: bool, engine: str | None) -> None:
    """Build the full wiki for all registered PDF sources."""
    from pdf_to_wiki.ingest.extract_toc import extract_toc
    from pdf_to_wiki.ingest.extract_page_labels import extract_page_labels as extract_pl
    from pdf_to_wiki.ingest.build_section_tree import build_section_tree
    from pdf_to_wiki.ingest.extract_text import extract_text
    from pdf_to_wiki.emit.markdown_writer import emit_skeleton, emit_global_index
    from pdf_to_wiki.cache.db import CacheDB

    cfg = ctx.obj["config"]

    # Get all registered PDFs
    db = CacheDB(cfg.resolved_cache_db_path())
    sources = db.list_pdf_sources()
    db.close()

    if not sources:
        click.echo("No registered PDFs found. Run 'register' first.", err=True)
        raise SystemExit(1)

    click.echo(f"=== Building all ({len(sources)} PDFs) ===")
    click.echo()

    for src in sources:
        source_id = src.source_id
        click.echo(f"--- Building {source_id} ---")
        step_force = force

        # Run each step
        try:
            extract_toc(source_id, cfg, force=step_force)
            extract_pl(source_id, cfg, force=step_force)
            build_section_tree(source_id, cfg, force=step_force)
            extract_text(source_id, cfg, force=step_force, engine=engine)
            emit_skeleton(source_id, cfg, force=force)
            click.echo(f"  {source_id}: done")
        except Exception as e:
            click.echo(f"  {source_id}: FAILED - {e}", err=True)

        click.echo()

    # Generate global wiki index
    click.echo("Generating global wiki index...")
    emit_global_index(cfg)
    click.echo("\n=== All builds complete ===")


@main.command(name="repair")
@click.argument("source_id")
@click.option("--force", is_flag=True, help="Force re-emission with repair")
@click.pass_context
def repair(ctx: click.Context, source_id: str, force: bool) -> None:
    """Re-emit Markdown with repair/normalization applied."""
    from pdf_to_wiki.emit.markdown_writer import emit_skeleton

    cfg = ctx.obj["config"]
    manifest = emit_skeleton(source_id, cfg, force=True)
    click.echo(f"Repaired and re-emitted {len(manifest)} notes for {source_id}")


@main.command(name="glossary")
@click.argument("source_id")
@click.option("--force", is_flag=True, help="Force re-extraction")
@click.option("--emit", is_flag=True, help="Also emit glossary.md alongside wiki output")
@click.pass_context
def glossary(ctx: click.Context, source_id: str, force: bool, emit: bool) -> None:
    """Extract glossary entries from the PDF's text content."""
    from pdf_to_wiki.cache.db import CacheDB
    from pdf_to_wiki.cache.artifact_store import ArtifactStore
    from pdf_to_wiki.cache.manifests import StepManifestStore
    from pdf_to_wiki.ingest.extract_text import extract_text
    from pdf_to_wiki.repair.extract_glossary import extract_glossary as extract_gloss
    from pdf_to_wiki.models import SectionTree

    cfg = ctx.obj["config"]

    # Check cache
    artifacts = ArtifactStore(cfg.resolved_artifact_dir())
    step = "glossary"
    should_force = force

    if not should_force:
        cached = artifacts.load_json(source_id, "glossary")
        if cached is not None:
            click.echo(f"Glossary for {source_id} already extracted ({len(cached)} entries). Use --force to re-extract.")
            if emit:
                from pdf_to_wiki.repair.extract_glossary import emit_glossary_md
                emit_glossary_md(source_id, cfg)
            return

    # Ensure text is extracted
    db = CacheDB(cfg.resolved_cache_db_path())
    source = db.get_pdf_source(source_id)
    db.close()
    if source is None:
        click.echo(f"No registered PDF with source_id={source_id!r}.", err=True)
        raise SystemExit(1)

    # Extract text if needed
    text_data = artifacts.load_json(source_id, "extract_text")
    if text_data is None:
        click.echo("No extracted text found. Running text extraction first...")
        text_data = extract_text(source_id, cfg, force=False)
    else:
        text_data = {k: v for k, v in text_data.items()}

    # Load section tree
    tree_data = artifacts.load_json(source_id, "section_tree")
    if tree_data is None:
        click.echo(f"No section tree for {source_id}. Run 'build-section-tree' first.", err=True)
        raise SystemExit(1)
    tree = SectionTree(**tree_data)

    # Extract glossary
    entries = extract_gloss(text_data, tree, cfg)

    # Save artifact
    glossary_data = [e.to_dict() for e in entries]
    artifacts.save_json(source_id, "glossary", glossary_data)

    # Track in manifest
    manifests = StepManifestStore(CacheDB(cfg.resolved_cache_db_path()))
    manifests.mark_completed(source_id, step, artifact_path=f"{source_id}/glossary.json")
    # manifests store closes its db

    click.echo(f"Extracted {len(entries)} glossary entries for {source_id}")
    click.echo()
    for entry in entries[:20]:
        defn = entry.definition[:60] + ("..." if len(entry.definition) > 60 else "")
        click.echo(f"  **{entry.term}** — {defn}")
    if len(entries) > 20:
        click.echo(f"  ... and {len(entries) - 20} more")

    if emit:
        from pdf_to_wiki.repair.extract_glossary import emit_glossary_md
        result_path = emit_glossary_md(source_id, cfg)
        click.echo(f"\nEmitted glossary: {result_path}")


@main.command(name="entities")
@click.argument("source_id")
@click.option("--force", is_flag=True, help="Force regeneration of entity pages")
@click.pass_context
def entities(ctx: click.Context, source_id: str, force: bool) -> None:
    """Generate entity stub pages from glossary entries.

    Creates cross-reference stub pages under books/<source_id>/entities/
    for each glossary term, linking back to the source definition section(s).
    Also generates an entities/index.md with alphabetical navigation.

    Requires glossary extraction to have been run first ('pdf-to-wiki glossary').
    """
    from pdf_to_wiki.emit.entity_pages import generate_entity_pages

    cfg = ctx.obj["config"]

    # Check that glossary data exists
    from pdf_to_wiki.cache.artifact_store import ArtifactStore
    artifacts = ArtifactStore(cfg.resolved_artifact_dir())
    glossary_data = artifacts.load_json(source_id, "glossary")
    if not glossary_data:
        click.echo(f"No glossary data for {source_id}. Run 'pdf-to-wiki glossary' first.", err=True)
        raise SystemExit(1)

    manifest = generate_entity_pages(source_id, cfg, force=force)
    click.echo(f"Generated {len(manifest)} entity pages for {source_id}")
    click.echo()
    for term, path in sorted(manifest.items()):
        click.echo(f"  {term} → {path}")


@main.command(name="validate")
@click.argument("source_id", required=False)
@click.option("--all", "validate_all_flag", is_flag=True, help="Validate all registered PDFs")
@click.pass_context
def validate(ctx: click.Context, source_id: str | None, validate_all_flag: bool) -> None:
    """Validate emitted wiki for broken links, missing images, and orphans."""
    from pdf_to_wiki.emit.validate import validate_wiki, validate_all as v_all

    cfg = ctx.obj["config"]

    if validate_all_flag:
        reports = v_all(cfg)
        for sid, report in reports.items():
            click.echo(report.summary())
            click.echo()
    elif source_id:
        report = validate_wiki(source_id, cfg)
        click.echo(report.summary())
        if not report.is_clean:
            raise SystemExit(1)
    else:
        click.echo("Provide a source_id or use --all", err=True)
        raise SystemExit(1)


@main.command(name="diagnose")
@click.argument("source_id")
@click.option("--pages", default=None, help="Page range to diagnose (e.g., '1-10')")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON instead of text")
@click.pass_context
def diagnose(ctx: click.Context, source_id: str, pages: str | None, as_json: bool) -> None:
    """Diagnose font and encoding issues in a registered PDF.

    Scans the PDF for all fonts and character codes used on each page.
    Reports unusual characters, symbol/dingbat fonts, and encoding issues.
    Useful for debugging garbled text from PDFs with unusual encodings.
    """
    from pdf_to_wiki.cache.db import CacheDB
    from pdf_to_wiki.ingest.diagnostics import diagnose_fonts

    cfg = ctx.obj["config"]

    db = CacheDB(cfg.resolved_cache_db_path())
    source = db.get_pdf_source(source_id)
    db.close()
    if source is None:
        click.echo(f"No registered PDF with source_id={source_id!r}.", err=True)
        raise SystemExit(1)

    page_range = _parse_page_range(pages) if pages else None
    if page_range and page_range[0] >= 1:
        # Convert 1-indexed user input to 0-indexed
        page_range = (page_range[0] - 1, page_range[1] - 1)

    output = diagnose_fonts(
        source.path,
        page_range=page_range,
        output_format="json" if as_json else "text",
    )
    click.echo(output)


@main.command(name="tables")
@click.argument("source_id")
@click.option("--min-rows", default=2, type=int, help="Minimum data rows for a table")
@click.option("--min-cols", default=2, type=int, help="Minimum columns for a table")
@click.option("--section", default=None, help="Only extract tables from this section ID")
@click.option("--csv", "as_csv", is_flag=True, help="Output as CSV instead of JSON")
@click.option("--force", is_flag=True, help="Force re-extraction")
@click.pass_context
def tables(ctx: click.Context, source_id: str, min_rows: int, min_cols: int, section: str | None, as_csv: bool, force: bool) -> None:
    """Extract structured table data from a built wiki.

    Scans the extracted text for Markdown pipe tables and outputs
    them as structured JSON or CSV data. Useful for VTT import,
    spreadsheet export, or structured queries.

    Requires text extraction to have been run first.
    """
    from pdf_to_wiki.cache.artifact_store import ArtifactStore
    from pdf_to_wiki.cache.db import CacheDB
    from pdf_to_wiki.repair.structured_tables import (
        extract_pipe_tables,
        extract_structured_tables,
    )

    cfg = ctx.obj["config"]
    artifacts = ArtifactStore(cfg.resolved_artifact_dir())

    # Load extracted text
    text_data = artifacts.load_json(source_id, "extract_text")
    if not text_data:
        click.echo(f"No extracted text for {source_id}. Run 'build' first.", err=True)
        raise SystemExit(1)

    # Filter to single section if requested
    if section:
        text_data = {k: v for k, v in text_data.items() if section in k}
        if not text_data:
            click.echo(f"No sections matching '{section}'.", err=True)
            raise SystemExit(1)

    if not as_csv:
        import json
        result = extract_structured_tables(text_data, min_rows=min_rows, min_cols=min_cols)
        click.echo(json.dumps(result, indent=2))
        click.echo(f"\nFound {len(result)} tables from {source_id}", err=True)
    else:
        all_tables = extract_structured_tables(text_data, min_rows=min_rows, min_cols=min_cols)
        from pdf_to_wiki.repair.structured_tables import PipeTable
        for i, table_data in enumerate(all_tables):
            table = PipeTable(
                headers=table_data["headers"],
                rows=table_data["rows"],
                caption=table_data.get("caption", ""),
                section_id=table_data.get("section_id", ""),
            )
            if i > 0:
                click.echo()  # Blank line between tables
            if table.caption:
                click.echo(f"# {table.caption}")
            if table.section_id:
                click.echo(f"# Section: {table.section_id}")
            click.echo(table.to_csv())
        click.echo(f"Found {len(all_tables)} tables from {source_id}", err=True)


@main.command(name="build")
@click.argument("source_id")
@click.option("--force", is_flag=True, help="Force re-run all steps")
@click.option("--force-step", default=None, help="Force re-run of a specific step")
@click.option("--skip-extract", is_flag=True, help="Skip text extraction step (emit skeleton only)")
@click.option("--engine", default=None, help="Extraction engine: marker (default), pymupdf, or docling")
@click.option("--sections", default=None, help="Comma-separated section IDs or slugs to process")
@click.option("--page-range", default=None, help="Only process sections within page range (e.g., '10-50')")
@click.option("--no-validate", is_flag=True, help="Skip post-build validation")
@click.option("--glossary", is_flag=True, help="Extract glossary and emit glossary.md (auto-enabled for Marker/Docling engines)")
@click.pass_context
def build(ctx: click.Context, source_id: str, force: bool, force_step: str | None, skip_extract: bool, engine: str | None, sections: str | None, page_range: str | None, no_validate: bool, glossary: bool) -> None:
    """Run the full pipeline for a registered PDF source."""
    from pdf_to_wiki.ingest.extract_toc import extract_toc
    from pdf_to_wiki.ingest.extract_page_labels import extract_page_labels as extract_pl
    from pdf_to_wiki.ingest.build_section_tree import build_section_tree
    from pdf_to_wiki.ingest.extract_text import extract_text
    from pdf_to_wiki.emit.markdown_writer import emit_skeleton
    from pdf_to_wiki.cache.db import CacheDB

    cfg = ctx.obj["config"]
    step_force = force or (force_step is not None)
    section_filter = [s.strip() for s in sections.split(",")] if sections else None
    page_filter = _parse_page_range(page_range) if page_range else None
    engine_used = engine or cfg.extract_engine

    # Glossary extraction works best with engines that preserve bold/italic
    # (Marker and Docling). Auto-enable for those engines if not explicitly set.
    if glossary or (engine_used in ("marker", "docling") and not ctx.params.get("no_validate")):
        # Auto-enable glossary for Marker/Docling unless --glossary was explicitly False
        # --glossary flag explicitly requested it
        run_glossary = True
    else:
        run_glossary = glossary  # Only if explicitly requested

    # Verify the PDF is registered
    db = CacheDB(cfg.resolved_cache_db_path())
    source = db.get_pdf_source(source_id)
    db.close()
    if source is None:
        click.echo(f"No registered PDF with source_id={source_id!r}. Run 'register' first.", err=True)
        raise SystemExit(1)

    click.echo(f"=== Building {source_id} ===")
    click.echo(f"Source: {source.path} ({source.page_count} pages)")
    click.echo()

    click.echo("Step 1/7: Extracting TOC...")
    extract_toc(source_id, cfg, force=step_force)

    click.echo("Step 2/7: Extracting page labels...")
    extract_pl(source_id, cfg, force=step_force)

    click.echo("Step 3/7: Building section tree...")
    build_section_tree(source_id, cfg, force=step_force)

    if not skip_extract:
        click.echo(f"Step 4/7: Extracting text content (engine: {engine_used})...")
        extract_text(source_id, cfg, force=step_force, engine=engine)
    else:
        click.echo("Step 4/7: Skipping text extraction (--skip-extract)")

    click.echo("Step 5/7: Emitting Markdown notes...")
    manifest = emit_skeleton(source_id, cfg, force=force, force_step=force_step, section_filter=section_filter, page_filter=page_filter)

    # Step 6: Glossary extraction (if enabled)
    if run_glossary and not skip_extract:
        from pdf_to_wiki.cache.artifact_store import ArtifactStore
        from pdf_to_wiki.cache.manifests import StepManifestStore
        from pdf_to_wiki.repair.extract_glossary import extract_glossary as extract_gloss, emit_glossary_md
        from pdf_to_wiki.models import SectionTree

        click.echo("Step 6/7: Extracting glossary...")
        artifacts = ArtifactStore(cfg.resolved_artifact_dir())

        # Load text and tree for glossary extraction
        text_data = artifacts.load_json(source_id, "extract_text")
        tree_data = artifacts.load_json(source_id, "section_tree")

        if text_data and tree_data:
            tree = SectionTree(**tree_data)
            entries = extract_gloss(text_data, tree, cfg)

            # Save artifact
            glossary_data = [e.to_dict() for e in entries]
            artifacts.save_json(source_id, "glossary", glossary_data)

            # Track in manifest
            manifests = StepManifestStore(CacheDB(cfg.resolved_cache_db_path()))
            manifests.mark_completed(source_id, "glossary", artifact_path=f"{source_id}/glossary.json")

            # Emit glossary.md
            result_path = emit_glossary_md(source_id, cfg)
            click.echo(f"  Extracted {len(entries)} glossary entries → {result_path}")
        else:
            click.echo("  Skipped: no extracted text or section tree available")
    else:
        if skip_extract:
            click.echo("Step 6/7: Skipping glossary (--skip-extract)")
        else:
            click.echo("Step 6/7: Skipping glossary (use --glossary to enable)")

    click.echo("Step 7/7: Done!")
    click.echo(f"\n=== Build complete: {len(manifest)} notes emitted ===")

    # Auto-validate unless disabled
    if not no_validate:
        click.echo()
        click.echo("Validating build...")
        from pdf_to_wiki.emit.validate import validate_wiki
        report = validate_wiki(source_id, cfg)
        click.echo(report.summary())
        if not report.is_clean:
            click.echo("⚠ Build has issues. Run 'pdf-to-wiki validate' for details.", err=True)


if __name__ == "__main__":
    main()


def _parse_page_range(pr: str) -> tuple[int, int]:
    """Parse a page range string like '10-50' or '10' into (start, end)."""
    parts = pr.split("-", 1)
    try:
        start = int(parts[0].strip())
        end = int(parts[1].strip()) if len(parts) > 1 else start
        return (start, end)
    except ValueError:
        raise click.BadParameter(f"Invalid page range: {pr!r}. Use format 'START-END' or 'PAGE'.") from None