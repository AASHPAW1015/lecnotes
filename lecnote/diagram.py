"""Shared diagram layout.

The model emits {nodes, edges}; this module decides where everything goes.
Both renderers use it — `excalidraw.py` turns the result into an Excalidraw
scene, `render.py` draws it to a PNG — so a diagram looks the same either way.
"""

import textwrap
from dataclasses import dataclass, field

FONT_SIZE = 16
LINE_HEIGHT = 1.25
PAD_X, PAD_Y = 32, 24
MIN_W, MAX_W = 160, 280
MIN_H = 56
V_GAP, H_GAP = 90, 70
COMPONENT_GAP = 140

STYLES = {
    "start":    {"shape": "ellipse",   "bg": "#e9ecef",     "stroke": "#1e1e1e"},
    "step":     {"shape": "rectangle", "bg": "#a5d8ff",     "stroke": "#1971c2"},
    "decision": {"shape": "diamond",   "bg": "#ffec99",     "stroke": "#f08c00"},
    "result":   {"shape": "rectangle", "bg": "#b2f2bb",     "stroke": "#2f9e44"},
    "formula":  {"shape": "rectangle", "bg": "transparent", "stroke": "#6741d9"},
    "note":     {"shape": "rectangle", "bg": "transparent", "stroke": "#868e96"},
}
DEFAULT_KIND = "step"


def style_for(node: dict) -> dict:
    return STYLES.get(node.get("kind", DEFAULT_KIND), STYLES[DEFAULT_KIND])


def approx_width(text: str, size: int = FONT_SIZE) -> float:
    """Rough text width, good enough for hand-drawn Excalidraw fonts."""
    return len(text) * size * 0.52


@dataclass
class Node:
    id: str
    label: str
    note: str
    kind: str
    shape: str
    lines: list[str]
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0


@dataclass
class Layout:
    nodes: list[Node]
    edges: list[dict]
    width: float = 0.0
    height: float = 0.0
    title: str = ""
    by_id: dict = field(default_factory=dict)


def _wrap(text: str, max_px: float, measure) -> list[str]:
    """Greedy wrap using whatever width function the renderer supplies."""
    words = str(text).split()
    if not words:
        return [""]
    lines, cur = [], words[0]
    for word in words[1:]:
        trial = f"{cur} {word}"
        if measure(trial) <= max_px:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    # A single word longer than the box still has to break somewhere.
    out: list[str] = []
    for line in lines:
        if measure(line) <= max_px or len(line) <= 1:
            out.append(line)
        else:
            chars = max(4, int(len(line) * max_px / max(measure(line), 1)))
            out.extend(textwrap.wrap(line, width=chars) or [line])
    return out


def _measure_node(node: dict, measure) -> tuple[float, float, list[str]]:
    style = style_for(node)
    lines = _wrap(node.get("label", ""), MAX_W - PAD_X, measure)
    if node.get("note"):
        lines += _wrap(node["note"], MAX_W - PAD_X, measure)

    widest = max((measure(l) for l in lines), default=0)
    w = max(MIN_W, min(MAX_W, widest + PAD_X))
    h = max(MIN_H, len(lines) * FONT_SIZE * LINE_HEIGHT + PAD_Y)

    if style["shape"] == "diamond":  # text only fits the inscribed rectangle
        w, h = w * 1.5, h * 1.6
    elif style["shape"] == "ellipse":
        w, h = w * 1.25, h * 1.3
    return w, h, lines


def _layers(ids: list[str], edges: list[dict]) -> dict[str, int]:
    """Longest-path layering. The iteration cap keeps cycles from hanging."""
    layer = {i: 0 for i in ids}
    for _ in range(len(ids) + 1):
        changed = False
        for e in edges:
            a, b = e.get("from"), e.get("to")
            if a in layer and b in layer and layer[b] < layer[a] + 1:
                layer[b] = layer[a] + 1
                changed = True
        if not changed:
            break
    return layer


def _components(ids: list[str], edges: list[dict]) -> list[list[str]]:
    """Connected components over the undirected graph, in input order."""
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        a, b = e.get("from"), e.get("to")
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def layout(spec: dict, measure=None) -> Layout:
    """Position every node. `measure` returns the pixel width of a string."""
    measure = measure or approx_width

    raw_nodes = [n for n in spec.get("nodes", []) if n.get("id")]
    if not raw_nodes:
        raise ValueError("diagram spec has no nodes")
    ids = [n["id"] for n in raw_nodes]
    edges = [e for e in spec.get("edges", [])
             if e.get("from") in ids and e.get("to") in ids]

    nodes: dict[str, Node] = {}
    for n in raw_nodes:
        w, h, lines = _measure_node(n, measure)
        nodes[n["id"]] = Node(
            id=n["id"], label=str(n.get("label", "")), note=str(n.get("note", "")),
            kind=n.get("kind", DEFAULT_KIND), shape=style_for(n)["shape"],
            lines=lines, w=w, h=h,
        )

    layer = _layers(ids, edges)
    x_cursor = 0.0
    for comp in _components(ids, edges):
        rows: dict[int, list[str]] = {}
        for nid in comp:
            rows.setdefault(layer[nid], []).append(nid)

        row_w = {r: sum(nodes[n].w for n in ns) + H_GAP * (len(ns) - 1)
                 for r, ns in rows.items()}
        comp_w = max(row_w.values())

        y = 0.0
        for r in sorted(rows):
            ns = rows[r]
            tallest = max(nodes[n].h for n in ns)
            x = x_cursor + (comp_w - row_w[r]) / 2
            for nid in ns:
                node = nodes[nid]
                node.x = x
                node.y = y + (tallest - node.h) / 2
                x += node.w + H_GAP
            y += tallest + V_GAP
        x_cursor += comp_w + COMPONENT_GAP

    ordered = [nodes[i] for i in ids]
    return Layout(
        nodes=ordered, edges=edges,
        width=max((n.x + n.w for n in ordered), default=0),
        height=max((n.y + n.h for n in ordered), default=0),
        title=str(spec.get("title") or ""),
        by_id=nodes,
    )


def edge_points(src: Node, dst: Node) -> tuple[float, float, float, float]:
    """Anchor an arrow: bottom-to-top normally, side-to-side when not descending."""
    sx, sy = src.x + src.w / 2, src.y + src.h
    ex, ey = dst.x + dst.w / 2, dst.y
    if ey <= sy:
        sy = src.y + src.h / 2
        ey = dst.y + dst.h / 2
    return sx, sy, ex, ey
