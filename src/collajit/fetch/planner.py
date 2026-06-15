"""Turn theme terms + a target image into palette-spanning search queries.

This is the "smart" part of fetching. A mosaic can only reconstruct colours that
exist in its tile library, so given a target we read its dominant colours and emit
queries like ``"eyes brown"``, ``"eyes blue"``, ``"eyes dark"`` — budgeting the
requested image count across them in proportion to how much of the target each
colour covers. With no target, the terms are simply split evenly.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass

import numpy as np
from PIL import Image

#: Colour words we can append to a theme term, chosen to be good search adjectives.
_HUE_NAMES: list[tuple[str, float, float]] = [
    ("red", 0.96, 1.0),
    ("red", 0.0, 0.04),
    ("orange", 0.04, 0.09),
    ("yellow", 0.09, 0.18),
    ("green", 0.18, 0.45),
    ("teal", 0.45, 0.52),
    ("blue", 0.52, 0.68),
    ("purple", 0.68, 0.80),
    ("pink", 0.80, 0.96),
]


@dataclass
class PlannedQuery:
    query: str
    count: int


def _color_name(h: float, s: float, v: float) -> str:
    if v < 0.18:
        return "black"
    if s < 0.15:
        return "white" if v > 0.85 else "gray"
    if 0.04 <= h < 0.09 and v < 0.6:
        return "brown"
    for name, lo, hi in _HUE_NAMES:
        if lo <= h < hi:
            return name
    return "red"


def color_weights(img: Image.Image, *, sample: int = 64) -> dict[str, float]:
    """Fraction of the image occupied by each colour name (sums to ~1)."""
    small = img.convert("RGB").resize((sample, sample), Image.BILINEAR)
    arr = np.asarray(small, dtype=np.float32) / 255.0
    counts: dict[str, int] = {}
    for r, g, b in arr.reshape(-1, 3):
        h, s, v = colorsys.rgb_to_hsv(float(r), float(g), float(b))
        name = _color_name(h, s, v)
        counts[name] = counts.get(name, 0) + 1
    total = sum(counts.values()) or 1
    return {k: v / total for k, v in counts.items()}


def _top_colors(weights: dict[str, float], *, min_frac: float, max_colors: int):
    items = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    chosen = [(c, w) for c, w in items if w >= min_frac][:max_colors]
    return chosen or items[:1]


def plan_queries(
    terms: list[str],
    target: Image.Image | None,
    *,
    total: int,
    min_frac: float = 0.08,
    max_colors: int = 4,
) -> list[PlannedQuery]:
    """Build (query, count) pairs whose counts sum to ``total``.

    Each theme term gets an equal share of ``total``. With a target, a term's share
    is split across its dominant colours (plus a plain on-theme query); without one,
    the term gets a single plain query.
    """
    terms = [t.strip() for t in terms if t.strip()]
    if not terms:
        raise ValueError("at least one search term is required")
    total = max(total, len(terms))

    per_term = _split_evenly(total, len(terms))
    plans: list[PlannedQuery] = []

    if target is None:
        for term, n in zip(terms, per_term, strict=True):
            plans.append(PlannedQuery(term, n))
        return _coalesce(plans)

    colors = _top_colors(color_weights(target), min_frac=min_frac, max_colors=max_colors)
    color_total = sum(w for _c, w in colors) or 1.0
    for term, n in zip(terms, per_term, strict=True):
        # 30% of the term's budget stays on the plain theme; 70% spreads over colours.
        plain = max(1, round(n * 0.3))
        plans.append(PlannedQuery(term, plain))
        remaining = n - plain
        if remaining <= 0:
            continue
        weights = [w / color_total for _c, w in colors]
        alloc = _split_weighted(remaining, weights)
        for (color, _w), c in zip(colors, alloc, strict=True):
            if c > 0:
                plans.append(PlannedQuery(f"{term} {color}", c))
    return _coalesce(plans)


def _split_evenly(total: int, parts: int) -> list[int]:
    base, rem = divmod(total, parts)
    return [base + (1 if i < rem else 0) for i in range(parts)]


def _split_weighted(total: int, weights: list[float]) -> list[int]:
    if not weights:
        return []
    raw = [w * total for w in weights]
    floors = [int(x) for x in raw]
    rem = total - sum(floors)
    # Hand out the remainder to the largest fractional parts.
    order = sorted(range(len(weights)), key=lambda i: raw[i] - floors[i], reverse=True)
    for i in order[:rem]:
        floors[i] += 1
    return floors


def _coalesce(plans: list[PlannedQuery]) -> list[PlannedQuery]:
    """Merge duplicate query strings, summing counts; drop zero-count entries."""
    merged: dict[str, int] = {}
    for p in plans:
        if p.count > 0:
            merged[p.query] = merged.get(p.query, 0) + p.count
    return [PlannedQuery(q, c) for q, c in merged.items()]
