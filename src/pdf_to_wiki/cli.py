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


@main.command(name="build")
@click.argument("source_id")
@click.option("--force", is_flag=True, help="Force re-run all steps")
@click.option("--force-step", default=None, help="Force re-run of a specific step")
@click.option("--skip-extract", is_flag=True, help="Skip text extraction step (emit skeleton only)")
@click.option("--engine", default=None, help="Extraction engine: marker (default) or pymupdf")
@click.option("--sections", default=None, help="Comma-separated section IDs or slugs to process")
@click.option("--page-range", default=None, help="Only process sections within page range (e.g., '10-50')")
@click.pass_context
def build(ctx: click.Context, source_id: str, force: bool, force_step: str | None, skip_extract: bool, engine: str | None, sections: str | None, page_range: str | None) -> None:
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

    click.echo("Step 1/6: Extracting TOC...")
    extract_toc(source_id, cfg, force=step_force)

    click.echo("Step 2/6: Extracting page labels...")
    extract_pl(source_id, cfg, force=step_force)

    click.echo("Step 3/6: Building section tree...")
    build_section_tree(source_id, cfg, force=step_force)

    if not skip_extract:
        click.echo(f"Step 4/6: Extracting text content (engine: {engine or cfg.extract_engine})...")
        extract_text(source_id, cfg, force=step_force, engine=engine)
    else:
        click.echo("Step 4/6: Skipping text extraction (--skip-extract)")

    click.echo("Step 5/6: Emitting Markdown notes...")
    manifest = emit_skeleton(source_id, cfg, force=force, force_step=force_step, section_filter=section_filter, page_filter=page_filter)

    click.echo("Step 6/6: Done!")
    click.echo(f"\n=== Build complete: {len(manifest)} notes emitted ===")


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