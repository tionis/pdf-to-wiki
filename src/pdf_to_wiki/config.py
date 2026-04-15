"""Pipeline configuration loading and defaults."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass
class WikiConfig:
    """Configuration for the pdf-to-wiki pipeline."""

    output_dir: str = "./data/outputs/wiki"
    books_dir: str = "books"
    cache_db_path: str = "./data/cache/cache.db"
    artifact_dir: str = "./data/artifacts"
    llm_backend: str = "ollama"
    llm_default_model: str = "glm-5.1:cloud"
    llm_temperature: float = 0.0
    extract_engine: str = "marker"
    obsidian_emit_frontmatter: bool = True
    obsidian_emit_index_notes: bool = True
    dry_run: bool = False

    def resolved_output_dir(self) -> Path:
        return Path(self.output_dir).resolve()

    def resolved_cache_db_path(self) -> Path:
        return Path(self.cache_db_path).resolve()

    def resolved_artifact_dir(self) -> Path:
        return Path(self.artifact_dir).resolve()


_DEFAULT_CONFIG_LOCATIONS = [
    "pdf-to-wiki.toml",
    "pdf_to_wiki.toml",
]


def load_config(config_path: str | None = None) -> WikiConfig:
    """Load configuration from a TOML file, falling back to defaults.

    If config_path is provided, it is used directly.
    Otherwise, searches current directory for default config filenames.
    """
    cfg = WikiConfig()

    path = _resolve_config_path(config_path)
    if path is not None:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        _apply_toml(cfg, data)

    return cfg


def _resolve_config_path(explicit: str | None) -> Path | None:
    if explicit is not None:
        p = Path(explicit)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {explicit}")
        return p

    for name in _DEFAULT_CONFIG_LOCATIONS:
        p = Path(name)
        if p.exists():
            return p

    return None


def _apply_toml(cfg: WikiConfig, data: dict) -> None:
    """Merge parsed TOML data into a WikiConfig instance."""
    if "wiki" in data:
        wiki = data["wiki"]
        cfg.output_dir = wiki.get("output_dir", cfg.output_dir)
        cfg.books_dir = wiki.get("books_dir", cfg.books_dir)
        cfg.dry_run = wiki.get("dry_run", cfg.dry_run)

    if "cache" in data:
        cache = data["cache"]
        cfg.cache_db_path = cache.get("db_path", cfg.cache_db_path)
        cfg.artifact_dir = cache.get("artifact_dir", cfg.artifact_dir)

    if "llm" in data:
        llm = data["llm"]
        cfg.llm_backend = llm.get("backend", cfg.llm_backend)
        cfg.llm_default_model = llm.get("default_model", cfg.llm_default_model)
        cfg.llm_temperature = float(llm.get("temperature", cfg.llm_temperature))

    if "extract" in data:
        extract = data["extract"]
        cfg.extract_engine = extract.get("engine", cfg.extract_engine)

    if "obsidian" in data:
        obs = data["obsidian"]
        cfg.obsidian_emit_frontmatter = obs.get("emit_frontmatter", cfg.obsidian_emit_frontmatter)
        cfg.obsidian_emit_index_notes = obs.get("emit_index_notes", cfg.obsidian_emit_index_notes)