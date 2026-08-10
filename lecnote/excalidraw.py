"""Compile a node/edge spec into an Excalidraw clipboard scene.

The LLM emits only {nodes, edges}; layout comes from `diagram.py` and
Excalidraw's element schema is handled here. Asking a model for x/y coordinates
and arrow bindings directly is unreliable — this keeps the model's job trivial
and the output always valid.
"""

import json
import random
import string
import time

from . import diagram
from .diagram import FONT_SIZE, LINE_HEIGHT, PAD_X

FONT_FAMILY = 1  # hand-drawn


def _id() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=16))


def _seed() -> int:
    return random.randint(1, 2**31 - 1)


def _base(kind: str, x: float, y: float, w: float, h: float, style: dict) -> dict:
    return {
        "id": _id(),
        "type": kind,
        "x": round(x, 2), "y": round(y, 2),
        "width": round(w, 2), "height": round(h, 2),
        "angle": 0,
        "strokeColor": style["stroke"],
        "backgroundColor": style["bg"],
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": {"type": 3} if kind in ("rectangle", "diamond") else {"type": 2},
        "seed": _seed(),
        "version": 1,
        "versionNonce": _seed(),
        "isDeleted": False,
        "boundElements": [],
        "updated": int(time.time() * 1000),
        "link": None,
        "locked": False,
    }


def _text(content: str, x: float, y: float, w: float, h: float,
          color: str, container_id: str | None = None, size: int = FONT_SIZE) -> dict:
    el = _base("text", x, y, w, h, {"stroke": color, "bg": "transparent"})
    el.update({
        "text": content,
        "originalText": content,
        "fontSize": size,
        "fontFamily": FONT_FAMILY,
        "textAlign": "center" if container_id else "left",
        "verticalAlign": "middle" if container_id else "top",
        "containerId": container_id,
        "lineHeight": LINE_HEIGHT,
        "autoResize": container_id is None,
        "roundness": None,
    })
    return el


def build_scene(spec: dict) -> dict:
    lay = diagram.layout(spec)
    elements: list[dict] = []
    shape_of: dict[str, dict] = {}

    if lay.title:
        elements.append(_text(lay.title, 0, -80, len(lay.title) * 12, 30,
                              "#1e1e1e", size=24))

    for node in lay.nodes:
        style = diagram.STYLES.get(node.kind, diagram.STYLES[diagram.DEFAULT_KIND])
        shape = _base(node.shape, node.x, node.y, node.w, node.h, style)

        label = "\n".join(node.lines)
        text_h = len(node.lines) * FONT_SIZE * LINE_HEIGHT
        txt = _text(label, node.x + PAD_X / 2, node.y + (node.h - text_h) / 2,
                    node.w - PAD_X, text_h, "#1e1e1e", container_id=shape["id"])
        shape["boundElements"].append({"id": txt["id"], "type": "text"})

        shape_of[node.id] = shape
        elements += [shape, txt]

    for e in lay.edges:
        src_node, dst_node = lay.by_id[e["from"]], lay.by_id[e["to"]]
        src, dst = shape_of[e["from"]], shape_of[e["to"]]
        sx, sy, ex, ey = diagram.edge_points(src_node, dst_node)
        dx, dy = ex - sx, ey - sy

        arrow = _base("arrow", sx, sy, abs(dx), abs(dy),
                      {"stroke": "#1e1e1e", "bg": "transparent"})
        arrow.update({
            "points": [[0, 0], [round(dx, 2), round(dy, 2)]],
            "lastCommittedPoint": None,
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "startBinding": {"elementId": src["id"], "focus": 0, "gap": 4},
            "endBinding": {"elementId": dst["id"], "focus": 0, "gap": 4},
            "roundness": {"type": 2},
        })
        src["boundElements"].append({"id": arrow["id"], "type": "arrow"})
        dst["boundElements"].append({"id": arrow["id"], "type": "arrow"})
        elements.append(arrow)

        if e.get("label"):
            lbl = str(e["label"])
            lt = _text(lbl, sx + dx / 2, sy + dy / 2 - 10,
                       diagram.approx_width(lbl), FONT_SIZE * LINE_HEIGHT,
                       "#1e1e1e", container_id=arrow["id"], size=14)
            arrow["boundElements"].append({"id": lt["id"], "type": "text"})
            elements.append(lt)

    return {"type": "excalidraw/clipboard", "elements": elements, "files": {}}


GAP = 160  # blank canvas between diagrams pasted as one scene


def to_clipboard_json(specs) -> str:
    """One scene holding every diagram, laid out left to right.

    Excalidraw pastes a scene as a unit, so several procedures arrive as
    separate flowcharts on the canvas from a single paste.
    """
    if isinstance(specs, dict):
        specs = [specs]

    scene = None
    elements: list[dict] = []
    x_off = 0.0
    for spec in specs:
        built = build_scene(spec)
        scene = scene or built
        els = built["elements"]
        if not els:
            continue
        left = min(e["x"] for e in els)
        right = max(e["x"] + e.get("width", 0) for e in els)
        shift = x_off - left
        for e in els:
            e["x"] += shift  # arrow "points" are relative, so only x moves
        elements += els
        x_off += (right - left) + GAP

    scene = scene or build_scene(specs[0])
    scene["elements"] = elements
    return json.dumps(scene, ensure_ascii=False)


def parse_specs(raw: str) -> list[dict]:
    """Diagram specs from the model's reply, fences or not.

    Accepts the current {"diagrams": [...]} shape and a bare single diagram,
    so a model that ignores the wrapper still produces something usable.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in model output:\n{raw[:400]}")
    obj = json.loads(text[start:end + 1])

    specs = obj.get("diagrams") if isinstance(obj, dict) else None
    if not specs:
        specs = [obj]
    specs = [s for s in specs if s.get("nodes")]
    if not specs:
        raise ValueError("no diagram in model output had any nodes")
    return specs


def parse_spec(raw: str) -> dict:
    """First diagram only. Kept for callers that want exactly one."""
    return parse_specs(raw)[0]
