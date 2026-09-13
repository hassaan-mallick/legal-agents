"""Citation graph: briefs as hubs, the authorities they cite as nodes.

Built from a citation-verifier run folder. A case appears when it is cited by
two or more brief families (an adversarial twin counts with its original) or
when any brief's citation of it was flagged. Edge colour is the verdict for
that brief's citation, so a fabricated name on a real citation shows as a red
edge into a node that other briefs cite cleanly.

Force-directed layout in numpy, a few steps per frame while it is warm.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

VERDICT_TONE = {"RESOLVED": "ok", "NAME_MISMATCH": "bad", "UNRESOLVED": "warn", "NOT_CHECKED": "dim", "SKIPPED": "dim"}
FLAGGED = {"NAME_MISMATCH", "UNRESOLVED"}


@dataclass
class Node:
    id: str
    kind: str            # brief | case
    label: str
    sub: str = ""        # resolved name for cases
    tone: str = "dim"
    degree: int = 0
    flagged: bool = False


@dataclass
class Edge:
    a: int               # brief node index
    b: int               # case node index
    tone: str
    verdict: str
    written: str
    key: str             # finding key in that brief (c<i>)


@dataclass
class Graph:
    nodes: list[Node]
    edges: list[Edge]
    pos: np.ndarray                    # (n, 2)
    vel: np.ndarray
    heat: float = 1.0
    pan: tuple[float, float] = (0.0, 0.0)
    zoom: float = 1.0
    drag_node: int | None = None
    hover: int | None = None
    user_moved: bool = False
    by_case: dict[str, int] = field(default_factory=dict)
    by_brief: dict[str, int] = field(default_factory=dict)


def _family(doc_id: str) -> str:
    return re.sub(r"-fake\d+$", "", doc_id)


def _norm(citation: str) -> str:
    """'102 F. 3d 1273' and '102 F.3d 1273' are the same authority."""
    return re.sub(r"\s+", "", citation)


def build(run_dir: Path) -> Graph:
    briefs: dict[str, list[dict]] = {}
    for f in sorted(run_dir.glob("*.json")):
        if f.name == "run.json":
            continue
        d = json.loads(f.read_text())
        if d.get("findings") is None:
            continue
        briefs[d["doc_id"]] = d["findings"]

    families: dict[str, set[str]] = {}
    verdicts: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    shown: dict[str, str] = {}
    for doc_id, fs in briefs.items():
        for x in fs:
            c = _norm(x["citation"])
            shown.setdefault(c, x["citation"])
            families.setdefault(c, set()).add(_family(doc_id))
            verdicts.setdefault(c, set()).add(x["verdict"])
            if x.get("resolved_name") and c not in names:
                names[c] = x["resolved_name"]

    keep = {c for c, fam in families.items() if len(fam) >= 2 or (verdicts[c] & FLAGGED)}

    nodes: list[Node] = []
    by_brief: dict[str, int] = {}
    by_case: dict[str, int] = {}
    for doc_id in briefs:
        by_brief[doc_id] = len(nodes)
        nodes.append(Node(id=doc_id, kind="brief", label=doc_id.replace("recap-", ""), tone="accent"))
    for c in sorted(keep):
        vs = verdicts[c]
        tone = "bad" if "NAME_MISMATCH" in vs else "warn" if "UNRESOLVED" in vs else "ok" if "RESOLVED" in vs else "dim"
        by_case[c] = len(nodes)
        nodes.append(Node(id=c, kind="case", label=shown[c], sub=names.get(c, ""), tone=tone, flagged=bool(vs & FLAGGED)))

    edges: list[Edge] = []
    for doc_id, fs in briefs.items():
        seen = set()
        for i, x in enumerate(fs):
            c = _norm(x["citation"])
            if c not in keep or c in seen:
                continue
            seen.add(c)
            edges.append(Edge(a=by_brief[doc_id], b=by_case[c], tone=VERDICT_TONE.get(x["verdict"], "dim"),
                              verdict=x["verdict"], written=(x.get("written_name") or "")[:80], key=f"c{i}"))
    for e in edges:
        nodes[e.a].degree += 1
        nodes[e.b].degree += 1

    # drop briefs with no kept edges (keeps the picture readable)
    live = [i for i, n in enumerate(nodes) if n.degree > 0]
    remap = {old: new for new, old in enumerate(live)}
    nodes = [nodes[i] for i in live]
    edges = [Edge(remap[e.a], remap[e.b], e.tone, e.verdict, e.written, e.key) for e in edges if e.a in remap and e.b in remap]
    by_brief = {k: remap[v] for k, v in by_brief.items() if v in remap}
    by_case = {k: remap[v] for k, v in by_case.items() if v in remap}

    n = len(nodes)
    rng = np.random.default_rng(7)
    ang = rng.uniform(0, 2 * np.pi, n)
    rad = np.where(np.array([nd.kind == "brief" for nd in nodes]), 120.0, 260.0) * rng.uniform(0.7, 1.0, n)
    pos = np.stack([np.cos(ang) * rad, np.sin(ang) * rad], axis=1)
    return Graph(nodes=nodes, edges=edges, pos=pos, vel=np.zeros((n, 2)), by_case=by_case, by_brief=by_brief)


def step(g: Graph, dt: float = 1.0, iterations: int = 2) -> None:
    """A few Fruchterman-Reingold style steps; cools down, reheats on interaction."""
    if g.heat < 0.01 or len(g.nodes) == 0:
        return
    deg = np.array([nd.degree for nd in g.nodes], dtype=float)
    mass = 1.0 + np.sqrt(deg)
    ea = np.array([e.a for e in g.edges])
    eb = np.array([e.b for e in g.edges])
    is_brief = np.array([nd.kind == "brief" for nd in g.nodes])
    for _ in range(iterations):
        d = g.pos[:, None, :] - g.pos[None, :, :]
        dist2 = (d ** 2).sum(-1) + 1e-3
        np.fill_diagonal(dist2, np.inf)
        rep = (d / dist2[..., None]) * 2600.0
        force = rep.sum(1)
        # springs
        dv = g.pos[eb] - g.pos[ea]
        ln = np.sqrt((dv ** 2).sum(-1)) + 1e-6
        rest = 70.0
        f = ((ln - rest) * 0.08)[:, None] * dv / ln[:, None]
        np.add.at(force, ea, f)
        np.add.at(force, eb, -f)
        # gravity: briefs toward centre a little more, everything toward origin
        force -= g.pos * np.where(is_brief, 0.06, 0.03)[:, None]
        if g.drag_node is not None:
            force[g.drag_node] = 0
        g.vel = (g.vel + force / mass[:, None] * dt) * 0.82
        g.vel = np.clip(g.vel, -40 * g.heat, 40 * g.heat)
        if g.drag_node is not None:
            g.vel[g.drag_node] = 0
        g.pos += g.vel * dt
    g.heat *= 0.985


def fit(g: Graph, width: float, height: float, margin: float = 70.0) -> None:
    """Zoom and pan so the whole graph sits inside a width x height canvas."""
    if len(g.nodes) == 0:
        return
    lo = g.pos.min(0)
    hi = g.pos.max(0)
    span = np.maximum(hi - lo, 1.0)
    zoom = min((width - margin * 2) / span[0], (height - margin * 2) / span[1])
    g.zoom = float(max(0.25, min(2.5, zoom)))
    centre = (lo + hi) / 2
    g.pan = (float(-centre[0] * g.zoom), float(-centre[1] * g.zoom))
