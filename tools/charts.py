"""Portable text charts (Windows source fallback)."""
from __future__ import annotations

BLOCKS = "▁▂▃▄▅▆▇█"


def _scaled(values, width=28):
    top = max(values) if values else 0
    if top <= 0:
        return [0 for _ in values], 0
    return [max(0, min(width, int(round(v / top * width)))) for v in values], top


def bar_chart(pairs: dict) -> str:
    if not pairs:
        return ""
    items = list(pairs.items())
    top = max(abs(float(v)) for _, v in items) or 1.0
    label_width = max(len(str(k)) for k, _ in items)
    lines = []
    for key, value in items:
        value = float(value)
        fill = int(round(abs(value) / top * 32))
        lines.append("%-*s | %s%s %.4g" % (
            label_width, str(key), "#" * fill, "." * (32 - fill), value))
    return "\n".join(lines)


def line_chart(values) -> str:
    vals = [float(v) for v in values]
    if not vals:
        return ""
    rows, cols = 10, min(max(len(vals), 8), 60)
    top, bottom = max(vals), min(vals)
    span = (top - bottom) or 1.0
    grid = [[" " for _ in range(cols)] for _ in range(rows)]
    for x in range(cols):
        idx = int(round(x * (len(vals) - 1) / max(1, cols - 1)))
        y = int(round((vals[idx] - bottom) / span * (rows - 1)))
        grid[rows - 1 - y][x] = "*"
    lines = ["%9.3f | %s" % (top - (top - bottom) * r / (rows - 1), "".join(grid[r]))
             for r in range(rows)]
    lines.append(" " * 9 + " +" + "-" * cols)
    return "\n".join(lines)


def sparkline(values) -> str:
    vals = [float(v) for v in values]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    out = []
    for v in vals:
        idx = int(round((v - lo) / span * (len(BLOCKS) - 1)))
        out.append(BLOCKS[max(0, min(len(BLOCKS) - 1, idx))])
    return "".join(out)
