"""Markdown and Obsidian wiki emission."""

from .markdown_writer import emit_skeleton
from .obsidian_paths import section_path, section_note_path

__all__ = ["emit_skeleton", "section_path", "section_note_path"]