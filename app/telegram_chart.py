"""Telegram scan-result chart renderer.

The renderer is intentionally isolated from the scanner and database. It only
consumes the already-produced scan result dictionary and creates a temporary
PNG for Telegram. No scan data is persisted here.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
import math
import os

from PIL import Image, ImageDraw, ImageFont, ImageFilter


FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FONT_REGULAR = FONT_DIR / "DejaVuSans.ttf"
FONT_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"


def _font(size: int, bold: bool = False):
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "N/A"
    if value >= 1000:
        return f"{value / 1000:.2f}s"
    return f"{value:.1f}ms"


def _rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _gradient_area(base: Image.Image, polygon, top=(63, 215, 255, 120), bottom=(120, 95, 255, 12)):
    if len(polygon) < 3:
        return
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.polygon(polygon, fill=top)
    # Mask the polygon and apply a vertical alpha gradient.
    mask = Image.new("L", base.size, 0)
    md = ImageDraw.Draw(mask)
    md.polygon(polygon, fill=255)
    grad = Image.new("RGBA", base.size)
    px = grad.load()
    h = base.height
    for y in range(base.height):
        t = y / max(1, h - 1)
        a = int(top[3] * (1 - t) + bottom[3] * t)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        # A row-wide fill is cheaper than per-pixel work.
        ImageDraw.Draw(grad).line((0, y, base.width, y), fill=(r, g, b, a))
    base.alpha_composite(Image.composite(grad, Image.new("RGBA", base.size), mask))


def build_scan_chart(scan: dict, scheduled: bool = False) -> str | None:
    """Create a polished latency chart and return a temporary PNG path."""
    raw = scan.get("chart_results") or scan.get("results") or []
    points = []
    for item in raw:
        latency = _num(item.get("latency_ms"))
        if latency is not None and str(item.get("status", "")) == "ok":
            points.append((str(item.get("domain") or "Target"), latency))
    if not points:
        return None

    W, H, S = 1600, 900, 2
    img = Image.new("RGBA", (W*S, H*S), (7, 11, 20, 255))
    draw = ImageDraw.Draw(img)

    # Background: deep glass-like navy with a subtle radial glow.
    bg = Image.new("RGBA", img.size, (7, 11, 20, 255))
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((250*S, 20*S, 1500*S, 850*S), fill=(45, 95, 190, 55))
    gd.ellipse((-300*S, 360*S, 900*S, 1100*S), fill=(90, 50, 190, 28))
    glow = glow.filter(ImageFilter.GaussianBlur(90*S))
    bg.alpha_composite(glow)
    img = bg
    draw = ImageDraw.Draw(img)

    # Header.
    title = "Scheduled Scan" if scheduled else "Network Scan"
    draw.text((72*S, 52*S), "idontScanner", font=_font(38*S, True), fill=(238, 245, 255, 255))
    draw.text((72*S, 102*S), title, font=_font(22*S), fill=(143, 164, 192, 255))
    draw.text((1180*S, 62*S), "LATENCY ANALYTICS", font=_font(20*S, True), fill=(103, 214, 255, 255))

    successful_vals = [v for _, v in points]
    avg = _num(scan.get("average_ms")) or (sum(successful_vals) / len(successful_vals))
    best = min(points, key=lambda x: x[1])
    worst = max(points, key=lambda x: x[1])
    score = scan.get("score")

    # KPI cards.
    cards = [
        ("AVERAGE", _fmt_ms(avg), (53, 207, 255)),
        ("BEST", _fmt_ms(best[1]), (99, 235, 180)),
        ("WORST", _fmt_ms(worst[1]), (255, 133, 142)),
        ("SCORE", f"{score}/100" if score is not None else "N/A", (174, 143, 255)),
    ]
    x = 72*S
    for label, value, accent in cards:
        box = (x, 158*S, x + 330*S, 258*S)
        _rounded(draw, box, 22*S, (17, 24, 38, 235), (35, 50, 74, 255), 2*S)
        draw.rounded_rectangle((box[0], box[1], box[0]+7*S, box[3]), radius=4*S, fill=accent+(255,))
        draw.text((x+28*S, 177*S), label, font=_font(16*S, True), fill=(126, 149, 180, 255))
        draw.text((x+28*S, 207*S), value, font=_font(30*S, True), fill=(240, 246, 255, 255))
        x += 350*S

    # Chart area.
    left, top, right, bottom = 82*S, 315*S, 1518*S, 775*S
    _rounded(draw, (left, top, right, bottom), 28*S, (11, 17, 29, 220), (32, 48, 71, 255), 2*S)
    chart_left, chart_top, chart_right, chart_bottom = 132*S, 365*S, 1472*S, 720*S

    # Robust scale: cap extreme outliers so the normal latency shape remains visible.
    vals = successful_vals
    sorted_vals = sorted(vals)
    q95 = sorted_vals[max(0, int(len(sorted_vals) * 0.95) - 1)]
    ymax = max(100.0, q95 * 1.35, min(max(vals) * 1.05, q95 * 2.5))
    if max(vals) <= 100:
        ymax = 120
    elif max(vals) <= 250:
        ymax = 300
    elif max(vals) <= 500:
        ymax = 600
    else:
        ymax = max(600.0, q95 * 1.5)
    ymin = 0.0

    # Grid and Y labels.
    for i in range(5):
        t = i / 4
        y = chart_top + int(t * (chart_bottom - chart_top))
        draw.line((chart_left, y, chart_right, y), fill=(39, 55, 78, 150), width=1*S)
        val = ymax * (1 - t)
        label = f"{val:.0f}"
        draw.text((48*S, y-10*S), label, font=_font(15*S), fill=(108, 130, 159, 255))

    n = len(points)
    coords = []
    for i, (_, val) in enumerate(points):
        x = chart_left if n == 1 else chart_left + int(i * (chart_right-chart_left) / (n-1))
        clipped = min(val, ymax)
        y = chart_bottom - int((clipped-ymin) / max(1, ymax-ymin) * (chart_bottom-chart_top))
        coords.append((x, y))

    # Area gradient beneath line.
    polygon = [(coords[0][0], chart_bottom)] + coords + [(coords[-1][0], chart_bottom)]
    _gradient_area(img, polygon)
    draw = ImageDraw.Draw(img)

    # Glow line.
    line_layer = Image.new("RGBA", img.size, (0,0,0,0))
    ld = ImageDraw.Draw(line_layer)
    if len(coords) > 1:
        ld.line(coords, fill=(74, 211, 255, 130), width=10*S, joint="curve")
    line_layer = line_layer.filter(ImageFilter.GaussianBlur(10*S))
    img.alpha_composite(line_layer)
    draw = ImageDraw.Draw(img)
    if len(coords) > 1:
        draw.line(coords, fill=(86, 220, 255, 255), width=4*S, joint="curve")

    # Mark best/worst points without overwhelming the chart.
    best_idx = min(range(len(points)), key=lambda i: points[i][1])
    worst_idx = max(range(len(points)), key=lambda i: points[i][1])
    for idx, color, tag in [(best_idx, (94, 235, 181, 255), "BEST"), (worst_idx, (255, 126, 137, 255), "WORST")]:
        px, py = coords[idx]
        draw.ellipse((px-8*S, py-8*S, px+8*S, py+8*S), fill=color)
        label = f"{tag}  {_fmt_ms(points[idx][1])}"
        tw = draw.textbbox((0,0), label, font=_font(15*S, True))[2]
        tx = max(chart_left+8*S, min(px - tw//2, chart_right-tw-8*S))
        ty = max(chart_top+8*S, py-42*S)
        _rounded(draw, (tx-10*S, ty-6*S, tx+tw+10*S, ty+26*S), 10*S, (15, 23, 36, 245), color, 1*S)
        draw.text((tx, ty), label, font=_font(15*S, True), fill=(235, 242, 250, 255))

    # Footer summary.
    online = int(scan.get("ok", len(points)) or 0)
    total = int(scan.get("total", len(points)) or len(points))
    failed = int(scan.get("failed", max(0, total-online)) or 0)
    footer = f"{online}/{total} online  •  {failed} failed  •  {len(points)} latency samples"
    draw.text((82*S, 818*S), footer, font=_font(18*S, True), fill=(126, 150, 181, 255))
    draw.text((1200*S, 818*S), "VPS → Target", font=_font(18*S, True), fill=(86, 220, 255, 255))

    img = img.resize((W, H), Image.Resampling.LANCZOS).convert("RGB")
    tmp = NamedTemporaryFile(prefix="idontscanner-scan-", suffix=".jpg", delete=False)
    path = tmp.name
    tmp.close()
    img.save(path, "JPEG", quality=92, optimize=True, progressive=True)
    return path
