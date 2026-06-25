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
CHI_RHO_PATH = os.path.join(ASSETS_DIR, "chi_rho.png")

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


_CHI_RHO_CACHE: dict[tuple[int, tuple], Image.Image] = {}


def _get_chi_rho_image(size: int, color=ACCENT_COLOR) -> Image.Image | None:
    """Load assets/chi_rho.png, recolor it to `color`, scale to `size` px tall.

    The source PNG is expected to be a dark mark on transparency. We keep its
    alpha channel and fill the visible pixels with the target color so the mark
    reads as white on the black card. Cached per (size, color)."""
    cache_key = (size, tuple(color))
    if cache_key in _CHI_RHO_CACHE:
        return _CHI_RHO_CACHE[cache_key]
    if not os.path.exists(CHI_RHO_PATH):
        return None
    try:
        src = Image.open(CHI_RHO_PATH).convert("RGBA")
    except Exception:
        return None
    # Replace the visible pixels with `color`, keep alpha for shape.
    alpha = src.split()[-1]
    solid = Image.new("RGBA", src.size, tuple(color) + (255,))
    solid.putalpha(alpha)
    # Scale to target height, preserving aspect ratio.
    src_w, src_h = solid.size
    aspect = src_w / src_h
    new_h = size
    new_w = max(1, int(new_h * aspect))
    out = solid.resize((new_w, new_h), Image.LANCZOS)
    _CHI_RHO_CACHE[cache_key] = out
    return out


def _draw_chi_rho(img: Image.Image, cx: int, cy: int, size: int, color=ACCENT_COLOR):
    """Paste the chi-rho mark onto `img` centered at (cx, cy), `size` px tall."""
    chi_rho = _get_chi_rho_image(size, color)
    if chi_rho is None:
        return  # asset missing; render the card without the mark
    w, h = chi_rho.size
    img.paste(chi_rho, (cx - w // 2, cy - h // 2), chi_rho)


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
    # Chi-rho's vertical extent equals chi_rho_size (full top-to-bottom stem).
    chi_rho_size = 64
    y += 28 + chi_rho_size + 18 + 26 + 4 + 22 + 38

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
    _draw_chi_rho(img, center_x, chi_rho_cy, chi_rho_size)

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
