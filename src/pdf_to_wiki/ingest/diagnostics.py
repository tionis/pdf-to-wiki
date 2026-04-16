"""Font and encoding diagnostics for PDF files.

Provides a diagnostic dump of all fonts and character codes used
on each page. This is useful for debugging garbled text from
obscure PDFs with unusual font encodings.

This is a utility module — it's not part of the main pipeline.
It's accessed via the `diagnose` CLI command.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

import fitz  # PyMuPDF

from pdf_to_wiki.logging import get_logger

logger = get_logger(__name__)


def diagnose_fonts(
    pdf_path: str,
    page_range: tuple[int, int] | None = None,
    output_format: str = "text",
) -> str:
    """Diagnose font and encoding issues in a PDF.

    Scans each page for all fonts used and the characters they produce.
    Reports unusual characters, symbol/dingbat fonts, and encoding issues.

    Args:
        pdf_path: Path to the PDF file.
        page_range: Optional (start, end) 0-based page range. None = all pages.
        output_format: "text" for human-readable, "json" for machine-readable.

    Returns:
        Diagnostic output as a string.
    """
    doc = fitz.open(pdf_path)

    if page_range is not None:
        start, end = page_range
        end = min(end, doc.page_count - 1)
    else:
        start, end = 0, doc.page_count - 1

    # Per-font statistics
    font_stats: dict[str, dict] = {}  # font_name → stats dict
    # Per-page font usage
    page_fonts: dict[int, list[str]] = defaultdict(list)  # page_idx → [font_names]
    # Characters that look suspicious (control chars, unusual Unicode)
    suspicious_chars: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    # font_name → [(page_idx, char, context)]

    total_chars = 0
    total_spans = 0

    for page_idx in range(start, end + 1):
        page = doc[page_idx]
        data = page.get_text("dict")

        for block in data.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    font = span.get("font", "unknown")
                    text = span.get("text", "")
                    size = span.get("size", 0)
                    flags = span.get("flags", 0)

                    total_spans += 1
                    total_chars += len(text)

                    # Track font usage
                    if font not in font_stats:
                        font_stats[font] = {
                            "char_count": 0,
                            "span_count": 0,
                            "sizes": Counter(),
                            "char_freq": Counter(),
                            "pages": set(),
                            "is_bold": False,
                            "is_italic": False,
                            "is_symbol": False,
                        }

                    fs = font_stats[font]
                    fs["char_count"] += len(text)
                    fs["span_count"] += 1
                    fs["sizes"][round(size, 1)] += 1
                    fs["pages"].add(page_idx)

                    # Track bold/italic
                    if flags & 2**4:  # bold flag
                        fs["is_bold"] = True
                    if flags & 2**1:  # italic flag
                        fs["is_italic"] = True

                    # Check for symbol/dingbat fonts
                    font_lower = font.lower()
                    if any(x in font_lower for x in ("ding", "symbol", "zapf", "wing", "math", "fantasy")):
                        fs["is_symbol"] = True

                    # Track character frequency
                    for ch in text:
                        fs["char_freq"][ch] += 1

                        # Detect suspicious characters
                        code = ord(ch)
                        if code < 32 and ch not in ("\n", "\r", "\t"):
                            # Control character (not common whitespace)
                            context = text[max(0, text.index(ch) - 5):text.index(ch) + 6]
                            suspicious_chars[font].append((page_idx, repr(ch), context))
                        elif 0x80 <= code <= 0x9F:
                            # C1 control characters (Latin-1 extensions masquerading as control)
                            context = text[max(0, text.index(ch) - 5):text.index(ch) + 6]
                            suspicious_chars[font].append((page_idx, repr(ch), context))
                        elif 0xE000 <= code <= 0xF8FF:
                            # Private use area — likely custom font glyphs
                            context = text[max(0, text.index(ch) - 5):text.index(ch) + 6]
                            suspicious_chars[font].append((page_idx, repr(ch), context))
                        elif 0xFFFD == code:
                            # Replacement character — encoding failure
                            context = text[max(0, text.index(ch) - 5):text.index(ch) + 6]
                            suspicious_chars[font].append((page_idx, repr(ch), context))

                    # Track page-font mapping
                    if font not in page_fonts[page_idx]:
                        page_fonts[page_idx].append(font)

    doc.close()

    if output_format == "json":
        return _format_json(font_stats, page_fonts, suspicious_chars,
                            start, end, total_chars, total_spans)
    else:
        return _format_text(font_stats, page_fonts, suspicious_chars,
                            start, end, total_chars, total_spans)


def _format_text(
    font_stats: dict,
    page_fonts: dict,
    suspicious_chars: dict,
    start: int,
    end: int,
    total_chars: int,
    total_spans: int,
) -> str:
    """Format diagnostics as human-readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("FONT & ENCODING DIAGNOSTICS")
    lines.append("=" * 60)
    lines.append(f"Pages: {start + 1}–{end + 1}")
    lines.append(f"Total characters: {total_chars:,}")
    lines.append(f"Total text spans: {total_spans:,}")
    lines.append(f"Distinct fonts: {len(font_stats)}")
    lines.append("")

    # Font summary table
    lines.append("-" * 60)
    lines.append("FONT SUMMARY")
    lines.append("-" * 60)
    # Sort by character count (most used first)
    for font, stats in sorted(font_stats.items(), key=lambda x: -x[1]["char_count"]):
        tags = []
        if stats["is_bold"]:
            tags.append("bold")
        if stats["is_italic"]:
            tags.append("italic")
        if stats["is_symbol"]:
            tags.append("⚠ SYMBOL")
        tag_str = f" [{', '.join(tags)}]" if tags else ""

        lines.append(f"  {font}{tag_str}")
        lines.append(f"    Characters: {stats['char_count']:,}  Spans: {stats['span_count']:,}")
        size_str = ", ".join(f"{s}×{c}" for s, c in stats["sizes"].most_common(5))
        lines.append(f"    Sizes: {size_str}")
        page_list = sorted(stats["pages"])
        if len(page_list) <= 10:
            lines.append(f"    Pages: {', '.join(str(p + 1) for p in page_list)}")
        else:
            lines.append(f"    Pages: {page_list[0] + 1}–{page_list[-1] + 1} ({len(page_list)} pages)")

        # Show unusual characters for this font (top 10 by frequency)
        unusual = []
        for ch, count in stats["char_freq"].most_common():
            code = ord(ch)
            if code < 32 and ch not in ("\n", "\r", "\t"):
                unusual.append((ch, count, code))
            elif 0x80 <= code <= 0x9F:
                unusual.append((ch, count, code))
            elif 0xE000 <= code <= 0xF8FF:
                unusual.append((ch, count, code))
            elif not ch.isalnum() and ch not in " \t\n\r.,;:!?-'\"()[]{}<>@#$%^&*+=|\\/_~`":
                unusual.append((ch, count, code))

        if unusual:
            unusual_str = ", ".join(
                f"{repr(ch)} (U+{code:04X})×{count}"
                for ch, count, code in unusual[:10]
            )
            lines.append(f"    Unusual chars: {unusual_str}")
        lines.append("")

    # Symbol/dingbat fonts detail
    symbol_fonts = {f: s for f, s in font_stats.items() if s["is_symbol"]}
    if symbol_fonts:
        lines.append("-" * 60)
        lines.append("⚠ SYMBOL/DINGBAT FONTS (detail)")
        lines.append("-" * 60)
        for font, stats in symbol_fonts.items():
            lines.append(f"  {font}:")
            # Show all character codes and their frequencies
            for ch, count in stats["char_freq"].most_common():
                code = ord(ch)
                lines.append(f"    {repr(ch):8s}  U+{code:04X}  ×{count}")
            lines.append("")

    # Suspicious characters
    if suspicious_chars:
        lines.append("-" * 60)
        lines.append("⚠ SUSPICIOUS CHARACTERS (control/private/use-area)")
        lines.append("-" * 60)
        for font, occurrences in suspicious_chars.items():
            if not occurrences:
                continue
            lines.append(f"  Font: {font}")
            # Show up to 20 examples
            for page_idx, char_repr, context in occurrences[:20]:
                lines.append(f"    Page {page_idx + 1}: {char_repr} in '{context}'")
            if len(occurrences) > 20:
                lines.append(f"    ... and {len(occurrences) - 20} more")
            lines.append("")

    # Per-page font usage summary
    lines.append("-" * 60)
    lines.append("PER-PAGE FONT USAGE (first 20 pages)")
    lines.append("-" * 60)
    for page_idx in sorted(page_fonts.keys())[:20]:
        fonts = page_fonts[page_idx]
        lines.append(f"  Page {page_idx + 1}: {', '.join(fonts)}")
    if len(page_fonts) > 20:
        lines.append(f"  ... ({len(page_fonts)} pages total)")

    return "\n".join(lines)


def _format_json(
    font_stats: dict,
    page_fonts: dict,
    suspicious_chars: dict,
    start: int,
    end: int,
    total_chars: int,
    total_spans: int,
) -> str:
    """Format diagnostics as JSON."""
    result = {
        "page_range": [start, end],
        "total_chars": total_chars,
        "total_spans": total_spans,
        "fonts": {},
        "page_fonts": {str(k): v for k, v in sorted(page_fonts.items())},
        "suspicious_chars": {},
    }

    for font, stats in font_stats.items():
        result["fonts"][font] = {
            "char_count": stats["char_count"],
            "span_count": stats["span_count"],
            "sizes": {str(s): c for s, c in stats["sizes"].most_common()},
            "is_bold": stats["is_bold"],
            "is_italic": stats["is_italic"],
            "is_symbol": stats["is_symbol"],
            "page_range": [min(stats["pages"]), max(stats["pages"])],
            "page_count": len(stats["pages"]),
            "char_freq": {
                f"U+{ord(ch):04X}": count
                for ch, count in stats["char_freq"].most_common(50)
            },
        }

    for font, occurrences in suspicious_chars.items():
        result["suspicious_chars"][font] = [
            {"page": page_idx, "char": char_repr, "context": context}
            for page_idx, char_repr, context in occurrences[:50]
        ]

    return json.dumps(result, indent=2)