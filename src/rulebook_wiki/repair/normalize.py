"""Repair and normalization pipeline for extracted text.

Applies deterministic fixes to extracted text before emission:

1. OCR word-break repair (split words like "vio lence" → "violence")
2. Heading normalization (strip Markdown formatting from headings)
3. Bullet list normalization (standardize bullet characters)
4. Page reference detection and annotation (for future wiki-link rewriting)
5. Whitespace and paragraph normalization
"""

from __future__ import annotations

import re
from rulebook_wiki.logging import get_logger

logger = get_logger(__name__)


def repair_text(text: str, tree: "SectionTree | None" = None) -> str:
    """Apply all repair/normalization steps to extracted text."""
    text = fix_ocr_word_breaks(text)
    text = normalize_bullets(text)
    text = normalize_whitespace(text)
    text = annotate_page_references(text)
    # Page reference rewriting requires section tree context
    if tree is not None:
        from rulebook_wiki.repair.rewrite_refs import rewrite_page_references
        text = rewrite_page_references(text, tree)
    return text


def fix_ocr_word_breaks(text: str) -> str:
    """Fix OCR-induced word breaks where a word is split with a space.

    Pattern: lowercase letter + space + lowercase letter (within same line)
    when the two halves form a known compound or when no dictionary is
    available, check if removing the space produces a valid word.

    Heuristic: If a line contains a pattern like "vio lence" or "accom plish"
    where both halves are lowercase and short (≤4 chars for the first half),
    try joining them. We're conservative — only join when:
    - First part is ≤5 chars
    - Second part continues immediately (no punctuation between)
    - Both parts are all-lowercase
    """
    # Pattern: word fragment (lowercase, 2-5 chars) + space + continuation (lowercase, 3+ chars)
    # Only apply when the fragment + continuation forms a plausible word.
    # We use a conservative approach: only fix common OCR split patterns.

    # Common OCR word-break patterns from Marker
    # These are suffixes that get split by OCR column/line detection
def fix_ocr_word_breaks(text: str) -> str:
    """Fix OCR-induced word breaks where a word is split with a space.

    Pattern: lowercase letter + space + lowercase letter (within same line)
    when the two halves form a known compound or when no dictionary is
    available, check if removing the space produces a valid word.

    Heuristic: If a line contains a pattern like "vio lence" or "accom plish"
    where both halves are lowercase and short, try joining them. We use
    suffix-based rules and verify the joined result is all-alpha lowercase.
    """
    # Pattern: word fragment (lowercase, 2-7 chars) + space + suffix (lowercase)
    # Only apply when the suffix is a known word-ending pattern.
    # IMPORTANT: suffixes must match only as complete suffixes, not prefixes.
    # E.g., "al" matches "also" prefix, so we require the combined word
    # to end at a word boundary.

    common_splits = [
        # -tion splits (2-7 char prefix)
        (r"(\w{2,7})\s+(tion|tions|tive|tively)\b", r"\1\2"),
        # -lence/-rence splits (violence, reference, difference, etc.)
        (r"(\w{2,7})\s+(lence|rence|sion|sure|plish|nish|tish|lish)\b", r"\1\2"),
        # -ment splits
        (r"(\w{3,7})\s+(ment|ments|mental)\b", r"\1\2"),
        # -ence/-ance splits
        (r"(\w{3,7})\s+(ence|ences|ance|ances)\b", r"\1\2"),
        # -ous/-ive splits
        (r"(\w{3,7})\s+(ous|ously|ive|ively|ivity)\b", r"\1\2"),
        # -able/-ible splits
        (r"(\w{3,7})\s+(able|ably|ible|ibly)\b", r"\1\2"),
        # -al/-ar splits — require \b to avoid matching "al" in "also"
        (r"(\w{3,7})\s+(ally)\b", r"\1\2"),  # only "ally" (not bare "al")
        (r"(\w{3,7})\s+(arly)\b", r"\1\2"),    # only "arly"
        # -ly splits on common adverbs (requires word boundary after)
        (r"(\w{3,8})\s+(ly)\b", r"\1\2"),
        # -ing splits
        (r"(\w{3,7})\s+(ing|ingly|ation|ations)\b", r"\1\2"),
        # -er/-est splits
        (r"(\w{3,7})\s+(er|ers|est)\b", r"\1\2"),
        # -ed splits
        (r"(\w{3,7})\s+(ed|edly|ening)\b", r"\1\2"),
        # -ful/-less splits
        (r"(\w{3,7})\s+(ful|fully|less|lessly)\b", r"\1\2"),
        # -ness splits
        (r"(\w{3,7})\s+(ness|nesses)\b", r"\1\2"),
        # -ize/-ise splits
        (r"(\w{3,7})\s+(ize|ized|izes|ise|ised|ises)\b", r"\1\2"),
    ]

    # Additional common English word splits that don't fit suffix patterns
    specific_splits = [
        # -ant/-ent adjective splits
        (r"(import)\s+(ant)\b", r"\1\2"),
        (r"(import)\s+(ance)\b", r"\1\2"),
        # -counter splits
        (r"(\ben)\s+(counter)\b", r"\1\2"),
        (r"(\bdis)\s+(count)\b", r"\1\2"),
        # -sider splits
        (r"(\bcon)\s+(sider)\b", r"\1\2"),
        (r"(\bcon)\s+(sideration)\b", r"\1\2"),
        # -petition splits
        (r"(\bcom)\s+(petition)\b", r"\1\2"),
        # -pelling splits
        (r"(\brap)\s+(pelling)\b", r"\1\2"),
        (r"(\bspell)\s+(ing)\b", r"\1\2"),
        # -less adjectives — but "much less" is two words, don't join
        (r"(end)\s+(less)\b", r"\1\2"),
        (r"(regard)\s+(less)\b", r"\1\2"),
        # -lish verbs
        (r"(\bestab)\s+(lish)\b", r"\1\2"),
        (r"(\bpun)\s+(lish)\b", r"\1\2"),
        # Common short-word splits
        (r"(\bhow)\s+(ever)\b", r"\1\2"),
        (r"(\bnever)\s+(the)\s+(less)\b", r"\1\2\3"),
        (r"(\bwhat)\s+(ever)\b", r"\1\2"),
        (r"(\bwhere)\s+(ever)\b", r"\1\2"),
        # -nish verbs
        (r"(\bfur)\s+(nish)\b", r"\1\2"),
        (r"(\bvan)\s+(ish)\b", r"\1\2"),
        # -plish
        (r"(\baccom)\s+(plish)\b", r"\1\2"),
        # Word-internal splits (common in OCR)
        (r"(\bcharac)\s+(ter)\b", r"\1\2"),
        (r"(\bcharac)\s+(ters)\b", r"\1\2"),
        (r"(\bfor)\s+(ward)\b", r"\1\2"),
        (r"(\bel)\s+(ement)\b", r"\1\2"),     # "el ement"
        (r"(\bel)\s+(ements)\b", r"\1\2"),   # "el ements"
    ]

    # Exclusions: word pairs that look like suffix splits but are real words
    exclusions = {
        "much less", "much lessly",
        "will less", "with less",
    }

    result = text
    for pattern, replacement in common_splits + specific_splits:
        # Only apply within lines (not across paragraphs)
        # Use a function to check that both sides are lowercase
        def _rejoin(m):
            prefix = m.group(1)
            suffix = m.group(2)
            # Only rejoin if prefix+suffix looks like a word (all lowercase, no space)
            joined = prefix + suffix
            # Skip if the original pair is in our exclusion list
            if f"{prefix} {suffix}" in exclusions:
                return m.group(0)  # Keep original
            if joined.isalpha() and joined.islower():
                return joined
            return m.group(0)  # Keep original

        result = re.sub(pattern, _rejoin, result)

    return result


def normalize_bullets(text: str) -> str:
    """Normalize bullet list markers to standard Markdown.

    Converts various bullet characters (•, ◦, ▪, ►, ‣, etc.) to
    standard Markdown `-` or `*` bullets, preserving indentation.

    When a line starts with multiple bullet characters (e.g., •• or •••),
    these are dot ratings (common in TTRPGs) — the first • becomes the
    list marker and subsequent • characters are preserved as ratings.
    """
    # Map of bullet characters to Markdown equivalents
    bullet_chars = "•◦▪►‣▸▹●○◎"
    bullet_re = re.compile(
        r"^(\s*)([" + re.escape(bullet_chars) + r"])([" + re.escape(bullet_chars) + r"]*)\s*",
        re.MULTILINE,
    )

    def _replace_bullet(m):
        indent = m.group(1)
        first_bullet = m.group(2)  # First bullet char (list marker)
        extra_dots = m.group(3)     # Additional bullet chars (dot rating)
        if extra_dots:
            # Multiple bullet chars = dot rating (••, •••, etc.)
            # First char becomes list marker, rest preserved as rating
            return f"{indent}- {extra_dots} "
        else:
            return f"{indent}- "

    return bullet_re.sub(_replace_bullet, text)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in extracted text.

    - Collapse runs of 2+ blank lines to 1 (i.e., max one blank line between paragraphs)
    - Strip trailing whitespace from lines
    - Ensure file ends with single newline
    """
    lines = text.split("\n")
    result: list[str] = []
    blank_count = 0

    for line in lines:
        stripped = line.rstrip()

        if not stripped:
            blank_count += 1
            if blank_count <= 1:
                result.append("")
        else:
            blank_count = 0
            result.append(stripped)

    return "\n".join(result).strip() + "\n"


def annotate_page_references(text: str) -> str:
    """Detect and annotate page references like 'p. 43' or 'see page 12'.

    Wraps references in a special annotation format for later wiki-link
    rewriting: [[page-ref:43]] becomes a link to the relevant section.

    This is a detection/annotation step. The actual wiki-link rewriting
    requires the section tree context and is done in a later step.
    """
    # Pattern: "p. NN", "pp. NN-NN", "see page NN", "on page NN"
    # Also "page NN" when not part of a different context
    patterns = [
        # "p. NN" or "pp. NN-NN"
        (r"\b[pP]{1,2}\.\s+(\d+(?:\s*[-–]\s*\d+)?)\b", r"{{page-ref:\1}}"),
        # "see page NN" or "on page NN"
        (r"\b(?:see|on|at|to)\s+page\s+(\d+)\b", r"{{page-ref:\1}}"),
    ]

    result = text
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result