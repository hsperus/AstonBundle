"""Tiny server-side SVG chart helpers (no JavaScript, works with a strict CSP)."""
from django.utils.html import escape
from django.utils.safestring import mark_safe

PLUM = "#2B1236"
PURPLE = "#5F0066"
GRID = "#E2DCD0"
MUTED = "#5B6270"


def _nice_max(v):
    if v <= 0:
        return 10
    for step in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000):
        if v <= step * 4:
            return step * ((int(v) // step) + 1)
    return int(v * 1.2)


def line_chart(points, width=760, height=260, label="Orders", highlight=None):
    """points: [(label, value)]. Returns an accessible inline SVG."""
    if not points:
        return mark_safe('<p class="muted small">No data yet.</p>')
    pad_l, pad_r, pad_t, pad_b = 44, 16, 16, 34
    w, h = width - pad_l - pad_r, height - pad_t - pad_b
    vmax = _nice_max(max(v for _, v in points))
    n = len(points)
    def x(i):
        return pad_l + (w * i / max(1, n - 1))
    def y(v):
        return pad_t + h - (h * v / vmax)
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)} chart" preserveAspectRatio="none">']
    for k in range(5):
        val = vmax * k / 4
        yy = y(val)
        parts.append(f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{yy + 4:.1f}" text-anchor="end" font-size="12" fill="{MUTED}">{int(val):,}</text>')
    area = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(points))
    parts.append(f'<polygon points="{pad_l},{pad_t + h} {area} {x(n - 1):.1f},{pad_t + h}" fill="{PURPLE}" opacity="0.10"/>')
    parts.append(f'<polyline points="{area}" fill="none" stroke="{PLUM}" stroke-width="3" stroke-linejoin="round"/>')
    step = max(1, n // 6)
    for i, (lab, v) in enumerate(points):
        if i % step == 0 or i == n - 1:
            parts.append(f'<text x="{x(i):.1f}" y="{height - 10}" text-anchor="middle" font-size="12" fill="{MUTED}">{escape(lab)}</text>')
    peak = max(range(n), key=lambda i: points[i][1])
    parts.append(f'<circle cx="{x(peak):.1f}" cy="{y(points[peak][1]):.1f}" r="5" fill="#FF6B4A" stroke="{PLUM}" stroke-width="2"/>')
    parts.append("</svg>")
    return mark_safe("".join(parts))


def forecast_chart(series, width=760, height=280):
    """series: {'history': [[iso, units]], 'forecast': [[iso, lo, mid, hi]], 'last_year': [[iso, units]]}"""
    hist = series.get("history", [])
    fc = series.get("forecast", [])
    if not hist and not fc:
        return mark_safe('<p class="muted small">No forecast yet.</p>')
    labels = [d for d, *_ in hist] + [d for d, *_ in fc]
    vals = [v for _, v in hist] + [hi for _, _, _, hi in fc]
    pad_l, pad_r, pad_t, pad_b = 44, 16, 16, 34
    w, h = width - pad_l - pad_r, height - pad_t - pad_b
    vmax = _nice_max(max(vals) if vals else 1)
    n = len(labels)
    def x(i):
        return pad_l + (w * i / max(1, n - 1))
    def y(v):
        return pad_t + h - (h * v / vmax)
    p = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Weekly units: actual history and forecast with 80% range" preserveAspectRatio="none">']
    for k in range(5):
        val = vmax * k / 4
        p.append(f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{y(val):.1f}" y2="{y(val):.1f}" stroke="{GRID}"/>')
        p.append(f'<text x="{pad_l - 8}" y="{y(val) + 4:.1f}" text-anchor="end" font-size="12" fill="{MUTED}">{int(val)}</text>')
    off = len(hist)
    if fc:
        top = " ".join(f"{x(off + i):.1f},{y(hi):.1f}" for i, (_, _, _, hi) in enumerate(fc))
        bot = " ".join(f"{x(off + i):.1f},{y(lo):.1f}" for i, (_, lo, _, _) in reversed(list(enumerate(fc))))
        p.append(f'<polygon points="{top} {bot}" fill="{PURPLE}" opacity="0.15"/>')
        mid = " ".join(f"{x(off + i):.1f},{y(m):.1f}" for i, (_, _, m, _) in enumerate(fc))
        if hist:
            mid = f"{x(off - 1):.1f},{y(hist[-1][1]):.1f} " + mid
        p.append(f'<polyline points="{mid}" fill="none" stroke="{PURPLE}" stroke-width="3" stroke-dasharray="8 6"/>')
    if hist:
        line = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(hist))
        p.append(f'<polyline points="{line}" fill="none" stroke="{PLUM}" stroke-width="3"/>')
        p.append(f'<line x1="{x(off - 1):.1f}" x2="{x(off - 1):.1f}" y1="{pad_t}" y2="{pad_t + h}" stroke="{MUTED}" stroke-dasharray="3 4"/>')
        p.append(f'<text x="{x(off - 1) + 6:.1f}" y="{pad_t + 12}" font-size="12" fill="{MUTED}">today</text>')
    step = max(1, n // 7)
    for i, d in enumerate(labels):
        if i % step == 0:
            from datetime import date
            dd = date.fromisoformat(d)
            lab = f"{dd.day} {dd.strftime('%b')}"
            p.append(f'<text x="{x(i):.1f}" y="{height - 10}" text-anchor="middle" font-size="12" fill="{MUTED}">{lab}</text>')
    p.append("</svg>")
    return mark_safe("".join(p))
