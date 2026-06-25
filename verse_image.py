"""
Verse image generator — renders a verse as a styled PNG image.

Branded for the Marcionite Church of Christ: black background, white
flourishes, a hand-drawn Chi-Rho in the footer, the church name and
website URL beneath it.
"""

import io
import os

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
FONT_REGULAR = os.path.join(ASSETS_DIR, "EBGaramond.ttf")
FONT_ITALIC = os.path.join(ASSETS_DIR, "EBGaramond-Italic.ttf")

# Image dimensions
WIDTH = 1200
PADDING = 80
TEXT_WIDTH = WIDTH - (PADDING * 2)

# Colors — black card with white flourishes
BG_COLOR = (10, 10, 12)           # near-black background
TEXT_COLOR = (240, 240, 235)      # near-white verse text
REF_COLOR = (210, 210, 205)       # slightly muted white for the reference
BORDER_COLOR = (165, 165, 160)    # muted white border
ACCENT_COLOR = (240, 240, 235)    # white flourishes / diamond / chi-rho
CHURCH_COLOR = (235, 235, 230)    # church name
URL_COLOR = (165, 165, 160)       # subtle URL

CHURCH_NAME = "Marcionite Church of Christ"
CHURCH_URL = "marcionitechurchofchrist.org"


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


def _draw_diamond_line(draw: ImageDraw.ImageDraw, cx: int, y: int, *,
                       dash_width: int = 200, diamond_size: int = 5, color=ACCENT_COLOR):
    """Horizontal line with a small diamond in the middle — used as a divider."""
    draw.line([(cx - dash_width, y), (cx + dash_width, y)], fill=color, width=1)
    draw.polygon(
        [
            (cx, y - diamond_size),
            (cx + diamond_size, y),
            (cx, y + diamond_size),
            (cx - diamond_size, y),
        ],
        fill=color,
    )


def _draw_chi_rho(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color=ACCENT_COLOR):
    """Draw the Chi-Rho Christogram centered at (cx, cy).

    Composition: a large chi (X) with a rho's stem rising upward through the
    intersection. The rho's bowl is a 'D'-shaped loop attached to the top of
    the stem, opening to the right.
    """
    line_w = max(3, size // 12)
    half = size // 2

    # Bowl geometry — sized so the loop sits at the top of the stem and the
    # stem itself extends well above the chi's intersection point.
    bowl_r = max(7, size // 4)
    bowl_top = cy - half - (bowl_r * 2) // 3  # how high the bowl reaches
    bowl_cy = bowl_top + bowl_r
    stem_top = bowl_cy  # the stem ends inside the bowl

    # Chi: two diagonals forming an X
    draw.line([(cx - half, cy + half), (cx + half, cy - half)], fill=color, width=line_w)
    draw.line([(cx - half, cy - half), (cx + half, cy + half)], fill=color, width=line_w)

    # Rho: vertical stem (goes through chi intersection up into the bowl)
    draw.line([(cx, cy + half), (cx, stem_top)], fill=color, width=line_w)

    # Rho: bowl — a "D" shape (right-half arc) attached to the stem.
    # Draw a circle outline then mask the left half with the stem itself;
    # easiest with an arc from -90 to 90 degrees.
    bbox = [cx - bowl_r, bowl_cy - bowl_r, cx + bowl_r, bowl_cy + bowl_r]
    draw.arc(bbox, start=-90, end=90, fill=color, width=line_w)


def render_verse(
    reference: str,
    verses: list[tuple[int, str]],
    section: str | None = None,
    hide_reference: bool = False,
) -> io.BytesIO:
    """Render verse(s) as a styled PNG image.

    Args:
        reference: e.g. "Evangelicon 1:1-3"
        verses: list of (verse_num, text)
        section: optional section heading
        hide_reference: if True, omit the section heading, reference, and
            divider lines (used for quiz cards). Branding still appears.

    Returns:
        BytesIO containing the PNG image data.
    """
    # Load fonts
    font_verse = ImageFont.truetype(FONT_REGULAR, 36)
    font_ref = ImageFont.truetype(FONT_ITALIC, 30)
    font_section = ImageFont.truetype(FONT_ITALIC, 26)
    font_church = ImageFont.truetype(FONT_REGULAR, 22)
    font_url = ImageFont.truetype(FONT_ITALIC, 18)

    line_spacing = 8
    verse_spacing = 16
    content_lines: list[tuple] = []

    if section and not hide_reference:
        content_lines.append(("section", section))
        content_lines.append(("gap", 12))

    for i, (vnum, text) in enumerate(verses):
        prefix = f"{vnum}  " if len(verses) > 1 else ""
        wrapped = _wrap_text(f"{prefix}{text}", font_verse, TEXT_WIDTH)
        for line in wrapped:
            content_lines.append(("verse", line))
        if i < len(verses) - 1:
            content_lines.append(("gap", verse_spacing))

    # Pre-calculate layout height
    y = PADDING + 30  # top padding + space for top divider

    for item_type, data in content_lines:
        if item_type == "section":
            bbox = font_section.getbbox(data)
            y += (bbox[3] - bbox[1]) + line_spacing
        elif item_type == "verse":
            bbox = font_verse.getbbox(data)
            y += (bbox[3] - bbox[1]) + line_spacing
        elif item_type == "gap":
            y += data

    # Space below content: divider + reference (optional) + branding (always).
    if not hide_reference:
        y += 50  # gap before bottom divider
        ref_bbox = font_ref.getbbox(reference)
        y += (ref_bbox[3] - ref_bbox[1])
    # Branding block: gap + chi-rho + gap + church name + url + bottom pad.
    # The chi-rho's bowl extends ~2/3 of bowl_r above its center, so we add
    # extra headroom there.
    chi_rho_size = 56
    chi_rho_overhang = chi_rho_size // 4 + 6  # how far the bowl rises above center
    y += 30 + (chi_rho_size + chi_rho_overhang) + 16 + 26 + 4 + 22 + 36

    height = max(420, y)

    # Create the image
    img = Image.new("RGB", (WIDTH, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Outer / inner borders
    border_inset = 20
    draw.rectangle(
        [border_inset, border_inset, WIDTH - border_inset, height - border_inset],
        outline=BORDER_COLOR, width=2,
    )
    inner_inset = 28
    draw.rectangle(
        [inner_inset, inner_inset, WIDTH - inner_inset, height - inner_inset],
        outline=BORDER_COLOR, width=1,
    )

    center_x = WIDTH // 2

    # Top flourish
    _draw_diamond_line(draw, center_x, PADDING - 10)

    # Draw verse content
    y = PADDING + 30
    for item_type, data in content_lines:
        if item_type == "section":
            bbox = font_section.getbbox(data)
            text_w = bbox[2] - bbox[0]
            draw.text(((WIDTH - text_w) // 2, y), data, fill=ACCENT_COLOR, font=font_section)
            y += (bbox[3] - bbox[1]) + line_spacing
        elif item_type == "verse":
            draw.text((PADDING, y), data, fill=TEXT_COLOR, font=font_verse)
            bbox = font_verse.getbbox(data)
            y += (bbox[3] - bbox[1]) + line_spacing
        elif item_type == "gap":
            y += data

    if not hide_reference:
        # Bottom flourish + reference
        y += 20
        _draw_diamond_line(draw, center_x, y)
        y += 20
        ref_bbox = font_ref.getbbox(reference)
        ref_w = ref_bbox[2] - ref_bbox[0]
        draw.text(((WIDTH - ref_w) // 2, y), reference, fill=REF_COLOR, font=font_ref)
        y += (ref_bbox[3] - ref_bbox[1])

    # --- Branding block, anchored to the bottom of the card ---
    # Recompute from the bottom up so it always sits the same distance from
    # the inner border regardless of how much content is above.
    branding_bottom_pad = 36
    url_bbox = font_url.getbbox(CHURCH_URL)
    church_bbox = font_church.getbbox(CHURCH_NAME)
    chi_rho_to_name_gap = 16
    name_to_url_gap = 4

    url_h = url_bbox[3] - url_bbox[1]
    church_h = church_bbox[3] - church_bbox[1]

    url_y = height - branding_bottom_pad - url_h
    church_y = url_y - name_to_url_gap - church_h
    # chi_rho_cy = center of the X — the rho's bowl extends ~chi_rho_overhang
    # pixels above this point, so leave that headroom between bowl and name.
    chi_rho_cy = church_y - chi_rho_to_name_gap - chi_rho_size // 2

    # Chi-Rho
    _draw_chi_rho(draw, center_x, chi_rho_cy, chi_rho_size)

    # Church name
    church_w = church_bbox[2] - church_bbox[0]
    draw.text(((WIDTH - church_w) // 2, church_y), CHURCH_NAME,
              fill=CHURCH_COLOR, font=font_church)

    # URL
    url_w = url_bbox[2] - url_bbox[0]
    draw.text(((WIDTH - url_w) // 2, url_y), CHURCH_URL,
              fill=URL_COLOR, font=font_url)

    # Save to BytesIO
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
