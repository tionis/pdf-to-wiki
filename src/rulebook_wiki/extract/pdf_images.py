"""Image extraction from PDFs — save images to wiki assets directory.

Extracts images from PDF pages and saves them as PNG files in the
wiki's assets directory. Matches Marker's image references
(`_page_N_Picture_X.jpeg`) with actual images extracted from
corresponding PDF pages using PyMuPDF.

This module works alongside Marker's Markdown output, which contains
image references like `![](_page_0_Picture_0.jpeg)`. Since Marker
provides the images as PIL objects only during a full re-conversion
(which is expensive), we extract them independently via PyMuPDF.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import fitz

from rulebook_wiki.logging import get_logger

logger = get_logger(__name__)


def extract_pdf_images(
    pdf_path: str,
    source_id: str,
    output_dir: Path,
) -> dict[str, str]:
    """Extract images from a PDF and save them to the wiki assets directory.

    Uses PyMuPDF to extract images from each page and saves them as PNG.
    The filenames are derived from Marker's naming convention
    (_page_N_Picture_X.jpeg) and matched by page position.

    Args:
        pdf_path: Path to the PDF file.
        source_id: The PDF source ID for namespacing.
        output_dir: The wiki output directory.

    Returns:
        Dict mapping Marker-style filenames (e.g., '_page_0_Picture_0.jpeg')
        to relative paths from the wiki root (e.g., 'assets/source_id/page_0_picture_0.png').
    """
    assets_dir = output_dir / "assets" / source_id
    assets_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    image_map: dict[str, str] = {}
    seen_hashes: dict[str, str] = {}  # Deduplicate by content hash

    for page_num in range(len(doc)):
        page = doc[page_num]
        images = page.get_images(full=True)

        for img_idx, img_info in enumerate(images):
            xref = img_info[0]

            # Extract image using PyMuPDF
            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue

            if base_image is None:
                continue

            image_bytes = base_image["image"]
            image_ext = base_image.get("ext", "png")

            # Deduplicate by content hash
            content_hash = hashlib.sha256(image_bytes).hexdigest()[:16]
            if content_hash in seen_hashes:
                # Reference the already-saved file
                marker_name = f"_page_{page_num}_Picture_{img_idx}.jpeg"
                image_map[marker_name] = seen_hashes[content_hash]
                continue

            # Save as PNG
            clean_name = f"page_{page_num}_picture_{img_idx}.png"
            save_path = assets_dir / clean_name

            # Convert to PNG if needed
            try:
                from PIL import Image
                import io
                img = Image.open(io.BytesIO(image_bytes))
                img.save(str(save_path), "PNG")
            except ImportError:
                # PIL not available — save raw bytes with original extension
                save_path = assets_dir / f"page_{page_num}_picture_{img_idx}.{image_ext}"
                save_path.write_bytes(image_bytes)
            except Exception as e:
                logger.debug(f"Skipping image {clean_name}: {e}")
                continue

            # Relative path from wiki root
            rel_path = f"assets/{source_id}/{clean_name}"

            # Map both the Marker filename pattern and variants
            marker_name = f"_page_{page_num}_Picture_{img_idx}.jpeg"
            image_map[marker_name] = rel_path
            # Also map without leading underscore and with Figure
            alt_name = f"_page_{page_num}_Figure_{img_idx}.jpeg"
            image_map[alt_name] = rel_path
            # Map .jpeg extension to .png in case Marker references differ
            marker_png = f"_page_{page_num}_Picture_{img_idx}.png"
            image_map[marker_png] = rel_path

            seen_hashes[content_hash] = rel_path

    doc.close()

    if image_map:
        logger.info(f"Extracted {len(set(image_map.values()))} unique images ({len(image_map)} references) from {pdf_path}")
    else:
        logger.info(f"No images extracted from {pdf_path}")

    return image_map


def rewrite_image_refs_in_sections(
    extracted: dict[str, str],
    image_map: dict[str, str],
) -> dict[str, str]:
    """Rewrite Marker image references in extracted section text.

    Converts references like ![](_page_0_Picture_0.jpeg) to
    proper relative paths like ![](../assets/source_id/page_0_picture_0.png).

    This rewrites to wiki-root-relative paths (assets/...), which
    are later made note-relative during emission.

    Args:
        extracted: Dict mapping section_id → extracted text with image refs.
        image_map: Dict mapping Marker filenames to wiki-root-relative paths.

    Returns:
        Updated dict with rewritten image references.
    """
    if not image_map:
        return extracted

    result: dict[str, str] = {}
    for section_id, text in extracted.items():
        result[section_id] = _rewrite_refs(text, image_map)

    return result


def _rewrite_refs(text: str, image_map: dict[str, str]) -> str:
    """Rewrite image references in a single text block."""

    def _replace(m):
        alt_text = m.group(1)
        original_ref = m.group(2)

        if original_ref in image_map:
            new_path = image_map[original_ref]
            return f"![{alt_text}]({new_path})"

        # Try without leading underscore
        clean_ref = original_ref.lstrip("_")
        for orig_key, new_path in image_map.items():
            if orig_key.lstrip("_") == clean_ref:
                return f"![{alt_text}]({new_path})"

        # Fallback: find any image from the same Marker page
        # Marker _page_N references don't correspond directly to PDF page N,
        # but we can look up any mapping entry that starts with _page_N_
        page_match = re.match(r"_page_(\d+)", original_ref)
        if page_match:
            page_num = page_match.group(1)
            prefix = f"_page_{page_num}_"
            for key, path in image_map.items():
                if key.startswith(prefix):
                    logger.debug(f"Fallback image match: {original_ref} -> {path}")
                    return f"![{alt_text}]({path})"

        # No match — leave as-is (broken reference)
        return m.group(0)

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _replace, text)