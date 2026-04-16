"""Glossary extraction from extracted text.

Deterministic, regex-based extraction of game terms and definitions
from text content. Works with both Marker output (which preserves
**bold** and *italic* formatting) and PyMuPDF output (plain text).

Extraction patterns:
1. **Lexicon/glossary sections** — Entire dedicated "Lexicon" or "Glossary"
   sections with **Term —** definition entries (common in Storypath/CoD).
2. **Inline bold definitions** — **Term**: definition patterns in body text.
3. **Structured fields** — **Field:** value patterns (Effect:, Prerequisites:, etc.)
   These are NOT glossary terms but game-mechanic metadata; they're extracted
   separately as structured field records.

The output is a Glossary artifact (glossary.json) mapping canonical term →
definition + provenance (section_id, page).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pdf_to_wiki.logging import get_logger

if TYPE_CHECKING:
    from pdf_to_wiki.config import WikiConfig
    from pdf_to_wiki.models import SectionTree

logger = get_logger(__name__)


# ── Data structures ──────────────────────────────────────────────────

# Known game-mechanic field labels that are NOT glossary terms.
# These are structured metadata (like "Effect:", "Cost:", "Prerequisites:").
# They're extracted separately via extract_structured_fields().
STRUCTURED_FIELD_LABELS: set[str] = {
    "Effect", "Description", "Prerequisites", "Prerequisite",
    "Success", "Failure", "Exceptional Success", "Dramatic Failure",
    "Cost", "Drawback", "Resolution", "Background",
    "Storytelling Hints", "Mission", "Methods", "Levels",
    "Sample actions", "Sample Specialties", "Sample contacts",
    "Novice", "Professional", "Experienced", "Expert", "Master",
    "Causing the Tilt", "Ending the Tilt", "Causing the Condition",
    "Ending the Condition", "The Truth",
    "Damage", "Dice Pool", "Roll Results",
    "Larceny", "Streetwise", "Stealth", "Crafts", "Subterfuge",
    "Academics", "Empathy", "Athletics", "Attribute Tasks", "Beat",
    # Note: "Action" is both a game term and a field label.
    # We keep it as a game term (glossary) by default.
    # "Action" omitted from structured fields to avoid ambiguity.
}

# Common false positives to skip (not game terms)
FALSE_POSITIVE_TERMS: set[str] = {
    "Example", "Note", "See Also", "See also", "See",
    "Table", "Figure", "Chapter", "Section", "Page",
    "Important", "Optional", "Required", "Recommended",
    "Special", "General", "Basic", "Advanced",
    "Personal", "Environmental", "Social", "Mental", "Physical",
    "Authors", "Developer", "Editor", "Artists",
    "Art Direction and Design", "Creative Director",
}

# Minimum definition length (chars) to consider a valid glossary entry
MIN_DEFINITION_LENGTH = 15


class GlossaryEntry:
    """A single glossary entry: term + definition + provenance."""

    __slots__ = ("term", "definition", "section_id", "page", "source_type")

    def __init__(
        self,
        term: str,
        definition: str,
        section_id: str = "",
        page: int | None = None,
        source_type: str = "lexicon",
    ) -> None:
        self.term = term
        self.definition = definition
        self.section_id = section_id
        self.page = page
        self.source_type = source_type  # "lexicon" | "inline" | "field"

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "definition": self.definition,
            "section_id": self.section_id,
            "page": self.page,
            "source_type": self.source_type,
        }

    def __repr__(self) -> str:
        return f"GlossaryEntry({self.term!r}, {self.source_type!r})"


class StructuredField:
    """A structured game-mechanic field: label + value + provenance."""

    __slots__ = ("label", "value", "section_id", "page")

    def __init__(
        self,
        label: str,
        value: str,
        section_id: str = "",
        page: int | None = None,
    ) -> None:
        self.label = label
        self.value = value
        self.section_id = section_id
        self.page = page

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "value": self.value,
            "section_id": self.section_id,
            "page": self.page,
        }


# ── Main extraction functions ────────────────────────────────────────


def extract_glossary(
    extracted_text: dict[str, str],
    tree: "SectionTree",
    config: "WikiConfig | None" = None,
) -> list[GlossaryEntry]:
    """Extract glossary entries from all sections' extracted text.

    Scans for three patterns:
    1. Lexicon/glossary sections: dedicated sections with **Term —** entries
    2. Inline bold definitions: **Term**: definition in body text
    3. Structured fields: **Field:** value (extracted separately)

    Deduplicates by lowercase term, preferring lexicon entries over inline.

    Args:
        extracted_text: Dict mapping section_id → extracted text content.
        tree: Section tree for page-range lookups.
        config: Optional pipeline configuration.

    Returns:
        List of GlossaryEntry objects, sorted by term (case-insensitive).
    """
    entries: dict[str, GlossaryEntry] = {}  # lowercase_term → entry

    for section_id, text in extracted_text.items():
        if not text or not text.strip():
            continue

        node = tree.nodes.get(section_id)
        page = node.pdf_page_start if node else None

        # 1. Check if this is a dedicated lexicon/glossary section
        is_lexicon = _is_lexicon_section(section_id, text)

        # 2. Extract **Term —** definition pattern (em-dash inside bold)
        for term, defn in _extract_emdash_definitions(text):
            if _is_valid_term(term, defn):
                key = term.lower()
                # Lexicon entries always win over inline
                if key not in entries or is_lexicon:
                    entries[key] = GlossaryEntry(
                        term=term,
                        definition=defn,
                        section_id=section_id,
                        page=page,
                        source_type="lexicon" if is_lexicon else "inline",
                    )

        # 3. Extract **Term**: definition pattern (colon separator)
        for term, defn in _extract_colon_definitions(text):
            label_upper = term.rstrip(":").strip()
            # Skip structured fields from glossary
            if label_upper in STRUCTURED_FIELD_LABELS:
                continue
            if _is_valid_term(term, defn):
                key = term.lower()
                if key not in entries:  # Don't override lexicon entries
                    entries[key] = GlossaryEntry(
                        term=term,
                        definition=defn,
                        section_id=section_id,
                        page=page,
                        source_type="inline",
                    )

        # 4. Extract **Term** — definition pattern (em-dash OUTSIDE bold)
        for term, defn in _extract_emdash_outside_definitions(text):
            if _is_valid_term(term, defn):
                key = term.lower()
                if key not in entries:
                    entries[key] = GlossaryEntry(
                        term=term,
                        definition=defn,
                        section_id=section_id,
                        page=page,
                        source_type="inline",
                    )

    result = sorted(entries.values(), key=lambda e: e.term.lower())
    logger.info(f"Extracted {len(result)} glossary entries from {len(extracted_text)} sections")
    return result


def extract_structured_fields(
    extracted_text: dict[str, str],
    tree: "SectionTree",
) -> list[StructuredField]:
    """Extract structured game-mechanic fields from text.

    These are **Field:** value patterns like:
    - **Effect:** Grants +2 to all Physical rolls.
    - **Prerequisites:** Strength 3, Brawl 2
    - **Cost:** 2 Experience

    Args:
        extracted_text: Dict mapping section_id → text.
        tree: Section tree for provenance.

    Returns:
        List of StructuredField objects.
    """
    fields: list[StructuredField] = []

    for section_id, text in extracted_text.items():
        if not text or not text.strip():
            continue

        node = tree.nodes.get(section_id)
        page = node.pdf_page_start if node else None

        for label, value in _extract_field_values(text):
            fields.append(StructuredField(
                label=label,
                value=value,
                section_id=section_id,
                page=page,
            ))

    logger.info(f"Extracted {len(fields)} structured field records")
    return fields


# ── Pattern extractors ────────────────────────────────────────────────


def _extract_emdash_definitions(text: str) -> list[tuple[str, str]]:
    """Extract **Term —** definition entries (em-dash INSIDE bold).

    Pattern: **Term —** Definition text here.

    This is the primary pattern for dedicated lexicon/glossary sections
    (e.g., CoD's Lexicon, Storypath's Glossary).
    """
    results = []
    # Match **Term —** or **Term –** (em-dash or en-dash inside bold)
    for m in re.finditer(r'\*\*([^*]+?)\s*[—–]+\s*\*\*\s*', text):
        term = m.group(1).strip()
        # Get definition text until next bold term or double blank line
        rest = text[m.end():]
        # Find next **...** or blank line break
        next_bold = re.search(r'\n\s*\*\*', rest)
        next_blank = re.search(r'\n\s*\n\s*\n', rest)
        end_markers = []
        if next_bold:
            end_markers.append(next_bold.start())
        if next_blank:
            end_markers.append(next_blank.start())
        if end_markers:
            end = min(end_markers)
        else:
            end = len(rest)

        defn = rest[:end].strip()
        if defn:
            results.append((term, defn))

    return results


def _extract_emdash_outside_definitions(text: str) -> list[tuple[str, str]]:
    """Extract **Term** — definition entries (em-dash OUTSIDE bold).

    Pattern: **Term** — Definition text here.

    Less common but found in some PDFs where the em-dash is outside
    the bold markers.
    """
    results = []
    for m in re.finditer(r'\*\*([^*]{2,80})\*\*\s*[—–]+\s*', text):
        term = m.group(1).strip()
        # Skip if term is a structured field
        if term.rstrip(":").strip() in STRUCTURED_FIELD_LABELS:
            continue
        rest = text[m.end():]
        next_bold = re.search(r'\n\s*\*\*', rest)
        next_blank = re.search(r'\n\s*\n\s*\n', rest)
        end_markers = []
        if next_bold:
            end_markers.append(next_bold.start())
        if next_blank:
            end_markers.append(next_blank.start())
        if end_markers:
            end = min(end_markers)
        else:
            end = min(len(rest), 500)

        defn = rest[:end].strip()
        if defn:
            results.append((term, defn))

    return results


def _extract_colon_definitions(text: str) -> list[tuple[str, str]]:
    """Extract **Term**: definition entries (colon separator).

    Pattern: **Term**: Definition text

    Excludes known structured-field labels; those are handled by
    extract_structured_fields().
    """
    results = []
    for m in re.finditer(r'\*\*([^*]{2,60})\*\*:\s*', text):
        term = m.group(1).strip()
        # Skip Marker page-reference artifacts
        if term.startswith("(p.") or term.startswith("(see p."):
            continue
        # Get definition text to end of line or next bold
        rest = text[m.end():]
        end_of_line = rest.find("\n")
        next_bold_on_line = re.search(r'\*\*', rest[:end_of_line]) if end_of_line > 0 else None

        if next_bold_on_line:
            defn = rest[:next_bold_on_line.start()].strip()
        elif end_of_line > 0:
            defn = rest[:end_of_line].strip()
        else:
            defn = rest[:200].strip()

        if defn:
            results.append((term, defn))

    return results


def _extract_field_values(text: str) -> list[tuple[str, str]]:
    """Extract **Field:** value pairs.

    Pattern: **Field:** value (value continues to end of line or next field).

    Only matches labels in the known STRUCTURED_FIELD_LABELS set.
    """
    results = []
    # Match **KnownField:** pattern
    for m in re.finditer(r'\*\*([^*]{2,40}):\*\*\s*', text):
        label = m.group(1).strip()
        if label not in STRUCTURED_FIELD_LABELS:
            continue
        # Get value text to end of line or next **
        rest = text[m.end():]
        end_of_line = rest.find("\n")
        next_bold = re.search(r'\*\*', rest[:end_of_line]) if end_of_line > 0 else None

        if next_bold:
            value = rest[:next_bold.start()].strip()
        elif end_of_line > 0:
            value = rest[:end_of_line].strip()
        else:
            value = rest[:200].strip()

        if value:
            results.append((label, value))

    return results


# ── Helpers ────────────────────────────────────────────────────────────


def _is_lexicon_section(section_id: str, text: str) -> bool:
    """Check if this section is a dedicated lexicon/glossary section.

    Identified by section_id containing 'lexicon' or 'glossary',
    or by the text starting with a heading like '# Lexicon' or '# Glossary'.
    """
    sid_lower = section_id.lower()
    if "lexicon" in sid_lower or "glossary" in sid_lower:
        return True
    # Check if the text starts with a lexicon/glossary heading
    first_200 = text[:200].lower()
    if re.search(r'^#+\s*(lexicon|glossary)\b', first_200):
        return True
    # Check if text has many **Term —** entries (5+ = lexicon)
    emdash_count = len(re.findall(r'\*\*[^*]+\s*[—–]+\s*\*\*', text))
    return emdash_count >= 5


def _is_valid_term(term: str, definition: str) -> bool:
    """Check if a term is a valid glossary entry.

    Filters out:
    - Too-short terms (< 2 chars)
    - Known false positives (common words, metadata)
    - Marker artifacts (page references, span IDs)
    - Terms with definition too short to be meaningful
    - Terms that are just numbers or punctuation
    """
    # Strip formatting artifacts
    term = term.strip()
    if not term or len(term) < 2:
        return False

    # Skip purely numeric/punctuation terms
    if re.match(r'^[\d\s.,;:!?—\–\-/()]+$', term):
        return False

    # Skip Marker page-reference artifacts
    if re.search(r'\(p\.\s*\d+\)', term) or re.search(r'\(see p\.\s*\d+\)', term):
        return False
    if re.search(r'#page-\d+', term):
        return False
    if term.startswith("[(") or term.startswith("(p.") or term.startswith("(see"):
        return False

    # Skip known false positives
    term_clean = term.rstrip(":").strip()
    if term_clean in FALSE_POSITIVE_TERMS:
        return False

    # Skip structured field labels (they go in structured_fields, not glossary)
    if term_clean in STRUCTURED_FIELD_LABELS:
        return False

    # Definition must be meaningful
    if len(definition.strip()) < MIN_DEFINITION_LENGTH:
        return False

    return True


# ── Glossary Markdown emission ────────────────────────────────────────


def emit_glossary_md(source_id: str, config: "WikiConfig") -> "Path":  # noqa: F821
    """Emit a glossary.md file for a source.

    Produces an alphabetical Markdown file listing all glossary entries
    with their definitions and links to the source sections.

    Args:
        source_id: The registered PDF source ID.
        config: Pipeline configuration.

    Returns:
        Path to the emitted glossary.md file.
    """
    from pathlib import Path

    from pdf_to_wiki.cache.artifact_store import ArtifactStore
    from pdf_to_wiki.emit.obsidian_paths import relative_markdown_link

    artifacts = ArtifactStore(config.resolved_artifact_dir())
    glossary_data = artifacts.load_json(source_id, "glossary")

    if not glossary_data:
        logger.warning(f"No glossary data for {source_id}. Run 'glossary' command first.")
        return Path("")

    # Load section tree for link computation
    tree_data = artifacts.load_json(source_id, "section_tree")
    if tree_data is None:
        logger.warning(f"No section tree for {source_id}. Cannot create glossary links.")
        tree = None
    else:
        from pdf_to_wiki.models import SectionTree
        tree = SectionTree(**tree_data)

    output_dir = config.resolved_output_dir()
    books_dir = config.books_dir
    glossary_path = output_dir / books_dir / source_id / "glossary.md"
    glossary_path.parent.mkdir(parents=True, exist_ok=True)

    # Build the glossary content
    lines = ["# Glossary", ""]
    lines.append(f"**{len(glossary_data)} terms extracted from {source_id}.**")
    lines.append("")

    # Alphabetical index of first letters for quick navigation
    letters = sorted(set(e["term"][0].upper() for e in glossary_data if e["term"]))
    if letters:
        lines.append("**Jump to:** " + " · ".join(f"[{l}](#{l.lower()})" for l in letters))
        lines.append("")

    # Group by first letter
    current_letter = None
    for entry_data in glossary_data:  # Already sorted alphabetically
        term = entry_data["term"]
        definition = entry_data["definition"]
        section_id = entry_data.get("section_id", "")
        source_type = entry_data.get("source_type", "lexicon")
        page = entry_data.get("page")

        first_letter = term[0].upper()
        if first_letter != current_letter:
            current_letter = first_letter
            lines.append(f"## {current_letter}")
            lines.append("")

        # Truncate very long definitions for readability
        if len(definition) > 300:
            defn_display = definition[:297] + "..."
        else:
            defn_display = definition

        # Build section link if tree is available
        source_ref = ""
        if tree and section_id and section_id in tree.nodes:
            node = tree.nodes[section_id]
            # Glossary is at books/source_id/glossary.md
            target_path = node.markdown_output_path or ""
            if target_path:
                from_path = f"{books_dir}/{source_id}/glossary.md"
                link = relative_markdown_link(from_path, target_path, node.title)
                page_label = node.printed_page_start or str(node.pdf_page_start)
                source_ref = f" — {link} (p. {page_label})"
            elif page is not None:
                source_ref = f" — p. {page}"
        elif page is not None:
            source_ref = f" — p. {page}"

        # Type badge
        type_badge = ""
        if source_type == "lexicon":
            type_badge = " *📖*"
        elif source_type == "inline":
            type_badge = " *📝*"

        lines.append(f"**{term}**{type_badge}: {defn_display}{source_ref}")
        lines.append("")

    glossary_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Emitted glossary: {glossary_path} ({len(glossary_data)} entries)")
    return glossary_path