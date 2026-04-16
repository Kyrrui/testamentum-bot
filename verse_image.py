"""
Verse image generator — renders a verse as a styled PNG image.
"""

import io
import os
import textwrap

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
FONT_REGULAR = os.path.join(ASSETS_DIR, "EBGaramond.ttf")
FONT_ITALIC = os.path.join(ASSETS_DIR, "EBGaramond-Italic.ttf")

# Image dimensions
WIDTH = 1200
PADDING = 80
TEXT_WIDTH = WIDTH - (PADDING * 2)

# Colors
BG_COLOR = (42, 36, 30)          # dark brown
TEXT_COLOR = (235, 220, 195)      # warm parchment
REF_COLOR = (180, 155, 120)       # muted gold
BORDER_COLOR = (120, 95, 65)      # medium brown
ACCENT_COLOR = (160, 130, 90)     # gold accent


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = font.getbbox(test_line)
        line_width = bbox[2] - bbox[0]
        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def render_verse(
    reference: str,
    verses: list[tuple[int, str]],
    section: str | None = None,
) -> io.BytesIO:
    """Render verse(s) as a styled PNG image.

    Args:
        reference: e.g. "Evangelicon 1:1-3"
        verses: list of (verse_num, text)
        section: optional section heading

    Returns:
        BytesIO containing the PNG image data.
    """
    # Load fonts
    font_verse = ImageFont.truetype(FONT_REGULAR, 36)
    font_num = ImageFont.truetype(FONT_REGULAR, 28)
    font_ref = ImageFont.truetype(FONT_ITALIC, 30)
    font_section = ImageFont.truetype(FONT_ITALIC, 26)
    font_watermark = ImageFont.truetype(FONT_ITALIC, 18)

    # Pre-calculate layout height
    line_spacing = 8
    verse_spacing = 16
    content_lines = []  # list of ("type", data)

    if section:
        content_lines.append(("section", section))
        content_lines.append(("gap", 12))

    for i, (vnum, text) in enumerate(verses):
        prefix = f"{vnum}  " if len(verses) > 1 else ""
        wrapped = _wrap_text(f"{prefix}{text}", font_verse, TEXT_WIDTH)
        for j, line in enumerate(wrapped):
            content_lines.append(("verse", line))
        if i < len(verses) - 1:
            content_lines.append(("gap", verse_spacing))

    # Calculate total height
    y = PADDING + 30  # top padding + space for decorative line

    for item_type, data in content_lines:
        if item_type == "section":
            bbox = font_section.getbbox(data)
            y += (bbox[3] - bbox[1]) + line_spacing
        elif item_type == "verse":
            bbox = font_verse.getbbox(data)
            y += (bbox[3] - bbox[1]) + line_spacing
        elif item_type == "gap":
            y += data

    # Add space for reference, decorative elements, and watermark
    y += 50  # gap before reference
    ref_bbox = font_ref.getbbox(reference)
    y += (ref_bbox[3] - ref_bbox[1])
    y += 60  # bottom padding + watermark

    height = max(400, y)

    # Create image
    img = Image.new("RGB", (WIDTH, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Decorative border
    border_inset = 20
    draw.rectangle(
        [border_inset, border_inset, WIDTH - border_inset, height - border_inset],
        outline=BORDER_COLOR,
        width=2,
    )

    # Inner border
    inner_inset = 28
    draw.rectangle(
        [inner_inset, inner_inset, WIDTH - inner_inset, height - inner_inset],
        outline=BORDER_COLOR,
        width=1,
    )

    # Top decorative line
    line_y = PADDING - 10
    center_x = WIDTH // 2
    dash_width = 200
    draw.line(
        [(center_x - dash_width, line_y), (center_x + dash_width, line_y)],
        fill=ACCENT_COLOR,
        width=1,
    )
    # Small diamond in center
    diamond_size = 5
    draw.polygon(
        [
            (center_x, line_y - diamond_size),
            (center_x + diamond_size, line_y),
            (center_x, line_y + diamond_size),
            (center_x - diamond_size, line_y),
        ],
        fill=ACCENT_COLOR,
    )

    # Draw content
    y = PADDING + 30

    for item_type, data in content_lines:
        if item_type == "section":
            bbox = font_section.getbbox(data)
            text_w = bbox[2] - bbox[0]
            x = (WIDTH - text_w) // 2  # center
            draw.text((x, y), data, fill=ACCENT_COLOR, font=font_section)
            y += (bbox[3] - bbox[1]) + line_spacing
        elif item_type == "verse":
            draw.text((PADDING, y), data, fill=TEXT_COLOR, font=font_verse)
            bbox = font_verse.getbbox(data)
            y += (bbox[3] - bbox[1]) + line_spacing
        elif item_type == "gap":
            y += data

    # Bottom decorative line
    y += 20
    draw.line(
        [(center_x - dash_width, y), (center_x + dash_width, y)],
        fill=ACCENT_COLOR,
        width=1,
    )
    draw.polygon(
        [
            (center_x, y - diamond_size),
            (center_x + diamond_size, y),
            (center_x, y + diamond_size),
            (center_x - diamond_size, y),
        ],
        fill=ACCENT_COLOR,
    )

    # Reference text (centered)
    y += 20
    ref_bbox = font_ref.getbbox(reference)
    ref_w = ref_bbox[2] - ref_bbox[0]
    draw.text(((WIDTH - ref_w) // 2, y), reference, fill=REF_COLOR, font=font_ref)

    # Watermark
    y = height - border_inset - 25
    wm_text = "Testamentum Bot"
    wm_bbox = font_watermark.getbbox(wm_text)
    wm_w = wm_bbox[2] - wm_bbox[0]
    draw.text(((WIDTH - wm_w) // 2, y), wm_text, fill=(80, 70, 55), font=font_watermark)

    # Save to BytesIO
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
