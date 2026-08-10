"""Draw a diagram spec straight to PNG with Pillow.

Same layout engine as the Excalidraw exporter, but rendered here — so a flowchart
can be pasted into Notion as an image without a round trip through Excalidraw.
No browser and no system libraries involved.
"""

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import diagram

SCALE = 2  # render at 2x for retina displays
MARGIN = 40
BG = "#ffffff"
# Enough for every fill, stroke and antialiased text edge; well past the point
# where more colours change what the eye sees on a diagram.
PALETTE_COLORS = 128
TEXT = "#1e1e1e"
ARROW = "#343a40"

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]
BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in (BOLD_CANDIDATES if bold else FONT_CANDIDATES):
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _measurer(font: ImageFont.FreeTypeFont):
    """Width function for the layout engine, in unscaled units."""
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def measure(text: str) -> float:
        return probe.textlength(text, font=font) / SCALE
    return measure


def _diamond(x: float, y: float, w: float, h: float) -> list[tuple[float, float]]:
    return [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]


def _arrowhead(sx: float, sy: float, ex: float, ey: float,
               size: float = 12 * SCALE) -> list[tuple[float, float]]:
    angle = math.atan2(ey - sy, ex - sx)
    spread = math.radians(26)
    return [
        (ex, ey),
        (ex - size * math.cos(angle - spread), ey - size * math.sin(angle - spread)),
        (ex - size * math.cos(angle + spread), ey - size * math.sin(angle + spread)),
    ]


def render(spec: dict) -> bytes:
    """Return PNG bytes for the given diagram spec."""
    body = _font(diagram.FONT_SIZE * SCALE)
    title_font = _font(26 * SCALE, bold=True)
    edge_font = _font(13 * SCALE)

    lay = diagram.layout(spec, measure=_measurer(body))

    title_h = 50 if lay.title else 0
    # A short procedure can carry a long title, so the canvas has to fit the
    # wider of the two or the heading is cut off at the right edge.
    title_w = (title_font.getlength(lay.title) if lay.title else 0) + MARGIN * 2 * SCALE
    width = int(max(lay.width * SCALE + MARGIN * 2 * SCALE, title_w))
    height = int(lay.height * SCALE + (MARGIN * 2 + title_h) * SCALE)

    img = Image.new("RGB", (max(width, 200), max(height, 200)), BG)
    draw = ImageDraw.Draw(img)

    ox = MARGIN * SCALE
    oy = (MARGIN + title_h) * SCALE

    if lay.title:
        draw.text((ox, MARGIN * SCALE // 2), lay.title, font=title_font, fill=TEXT)

    # Arrows first, so shapes cover the ends. Labels come last, on top of both.
    edge_labels: list[tuple[str, float, float]] = []
    for e in lay.edges:
        src, dst = lay.by_id[e["from"]], lay.by_id[e["to"]]
        sx, sy, ex, ey = diagram.edge_points(src, dst)
        sx, sy = sx * SCALE + ox, sy * SCALE + oy
        ex, ey = ex * SCALE + ox, ey * SCALE + oy

        # Stop short so the head sits against the shape, not inside it.
        length = math.hypot(ex - sx, ey - sy) or 1
        back = min(6 * SCALE, length / 3)
        ex_a = ex - (ex - sx) / length * back
        ey_a = ey - (ey - sy) / length * back

        draw.line([(sx, sy), (ex_a, ey_a)], fill=ARROW, width=2 * SCALE)
        draw.polygon(_arrowhead(sx, sy, ex_a, ey_a), fill=ARROW)

        if e.get("label"):
            # Sit the label nearer the source, and draw it after the shapes so a
            # long edge crossing another node cannot bury it.
            edge_labels.append((str(e["label"]),
                                sx + (ex - sx) * 0.35, sy + (ey - sy) * 0.35))

    for node in lay.nodes:
        style = diagram.STYLES.get(node.kind, diagram.STYLES[diagram.DEFAULT_KIND])
        fill = None if style["bg"] == "transparent" else style["bg"]
        x, y = node.x * SCALE + ox, node.y * SCALE + oy
        w, h = node.w * SCALE, node.h * SCALE
        stroke_w = 2 * SCALE

        if node.shape == "ellipse":
            draw.ellipse([x, y, x + w, y + h], fill=fill,
                         outline=style["stroke"], width=stroke_w)
        elif node.shape == "diamond":
            draw.polygon(_diamond(x, y, w, h), fill=fill, outline=style["stroke"])
            draw.line(_diamond(x, y, w, h) + [_diamond(x, y, w, h)[0]],
                      fill=style["stroke"], width=stroke_w)
        else:
            draw.rounded_rectangle([x, y, x + w, y + h], radius=8 * SCALE, fill=fill,
                                   outline=style["stroke"], width=stroke_w)

        line_h = diagram.FONT_SIZE * diagram.LINE_HEIGHT * SCALE
        block_h = len(node.lines) * line_h
        ty = y + (h - block_h) / 2
        for line in node.lines:
            tw = draw.textlength(line, font=body)
            draw.text((x + (w - tw) / 2, ty), line, font=body, fill=TEXT)
            ty += line_h

    for lbl, mx, my in edge_labels:
        tw = draw.textlength(lbl, font=edge_font)
        th = edge_font.size
        pad = 5 * SCALE
        draw.rectangle([mx - tw / 2 - pad, my - th / 2 - pad,
                        mx + tw / 2 + pad, my + th / 2 + pad], fill=BG)
        draw.text((mx - tw / 2, my - th / 2), lbl, font=edge_font, fill=TEXT)

    # A flowchart is flat fills, black text and a handful of pastels — nothing
    # like a photograph. A palette holds all of it exactly while cutting the
    # file to a fraction, which matters once a lecture yields several images.
    buf = io.BytesIO()
    img.quantize(colors=PALETTE_COLORS, method=Image.MEDIANCUT, dither=Image.NONE) \
       .save(buf, format="PNG", optimize=True)
    return buf.getvalue()
