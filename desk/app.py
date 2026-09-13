"""Legal Agents desk — a Dear ImGui operator console over real run output.

Run:  uv run python -m desk.app           (add --smoke to exit after 90 frames)

Reads the latest run of each agent under runs/, joins to corpus text, and shows
four docked panels: MATTER (documents), DOCUMENT (text with located quotes lit
up), FINDINGS (each claim with its verdict and quote), TRACE (the egress log:
every byte that left the machine). The HUD across the top shows model, route,
retention, tokens and cost. Nothing here is final; a named human decides.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

import numpy as np
from imgui_bundle import hello_imgui, imgui

from desk import graph as G
from desk.data import RUNS as ROOT_RUNS
from desk.data import Doc, Finding, Run, load_runs

# ---------------------------------------------------------------- palette
# A dark instrument panel rather than a website: near-black ground, one cool
# accent for selection, and semantic colours that mean something.
BG = (0.043, 0.055, 0.067, 1.0)
PANEL = (0.071, 0.090, 0.110, 1.0)
PANEL_2 = (0.094, 0.118, 0.141, 1.0)
LINE = (0.18, 0.22, 0.26, 1.0)
TEXT = (0.84, 0.88, 0.90, 1.0)
TEXT_DIM = (0.48, 0.55, 0.60, 1.0)
ACCENT = (0.31, 0.82, 0.88, 1.0)      # cyan: selection, cursor
OK = (0.24, 0.86, 0.52, 1.0)          # green: located / resolved
WARN = (0.96, 0.73, 0.26, 1.0)        # amber: unresolved
BAD = (1.0, 0.36, 0.36, 1.0)          # red: mismatch / escalated
DIM = (0.42, 0.48, 0.53, 1.0)         # grey: not checked / absent
TONE = {"ok": OK, "warn": WARN, "bad": BAD, "dim": DIM}


def col(c, a: float | None = None) -> int:
    r, g, b, ca = c
    return imgui.get_color_u32(imgui.ImVec4(r, g, b, ca if a is None else a))


def v4(c) -> imgui.ImVec4:
    return imgui.ImVec4(*c)


# ---------------------------------------------------------------- state
@dataclass
class Layout:
    width: float
    lines: list[tuple[int, int]]  # (start, end) char offsets per visual line


@dataclass
class State:
    runs: list[Run]
    run_ix: int = 0
    doc_ix: int = 0
    selected: str | None = None
    jump_to: str | None = None
    decisions: dict[str, str] = field(default_factory=dict)
    layouts: dict[tuple[str, int], Layout] = field(default_factory=dict)
    hud_t0: float = 0.0
    frames: int = 0
    smoke: bool = False
    font_ui: imgui.ImFont | None = None
    font_mono: imgui.ImFont | None = None
    font_doc: imgui.ImFont | None = None
    font_big: imgui.ImFont | None = None
    graphs: dict[str, G.Graph] = field(default_factory=dict)
    focus_graph: bool = False

    @property
    def run(self) -> Run:
        return self.runs[self.run_ix]

    @property
    def doc(self) -> Doc:
        return self.run.docs[self.doc_ix]

    def select_run(self, ix: int) -> None:
        self.run_ix, self.doc_ix, self.selected = ix, 0, None
        self.hud_t0 = time.time()

    def select_doc(self, ix: int) -> None:
        self.doc_ix, self.selected = ix, None

    def select(self, key: str | None) -> None:
        self.selected = key
        self.jump_to = key


S: State


# ---------------------------------------------------------------- text layout
def layout_text(text: str, width: float) -> list[tuple[int, int]]:
    """Greedy word wrap into (start, end) char ranges. Paragraph breaks kept."""
    lines: list[tuple[int, int]] = []
    space = imgui.calc_text_size(" ").x
    pos = 0
    for para in text.split("\n"):
        if not para.strip():
            lines.append((pos, pos))
            pos += len(para) + 1
            continue
        line_start = pos
        x = 0.0
        i = 0
        n = len(para)
        while i < n:
            j = i
            while j < n and para[j] != " ":
                j += 1
            word = para[i:j]
            w = imgui.calc_text_size(word).x
            if x > 0 and x + w > width:
                lines.append((line_start, pos + i - 1))
                line_start = pos + i
                x = 0.0
            x += w + space
            i = j + 1
        lines.append((line_start, pos + n))
        pos += n + 1
    return lines


def get_layout(doc: Doc, width: float) -> Layout:
    key = (doc.doc_id, int(width))
    lay = S.layouts.get(key)
    if lay is None:
        lay = Layout(width, layout_text(doc.text, width))
        S.layouts[key] = lay
    return lay


# ---------------------------------------------------------------- widgets
def badge(label: str, tone, mono: bool = True) -> None:
    dl = imgui.get_window_draw_list()
    if mono and S.font_mono:
        imgui.push_font(S.font_mono, 12.0)
    size = imgui.calc_text_size(label)
    p = imgui.get_cursor_screen_pos()
    pad = 5.0
    dl.add_rect_filled(p, imgui.ImVec2(p.x + size.x + pad * 2, p.y + size.y + 3), col(tone, 0.16), 3.0)
    dl.add_rect(p, imgui.ImVec2(p.x + size.x + pad * 2, p.y + size.y + 3), col(tone, 0.55), 3.0)
    dl.add_text(imgui.ImVec2(p.x + pad, p.y + 1.5), col(tone), label)
    imgui.dummy(imgui.ImVec2(size.x + pad * 2, size.y + 3))
    if mono and S.font_mono:
        imgui.pop_font()


def meter(frac: float, tone, width: float, height: float = 5.0) -> None:
    dl = imgui.get_window_draw_list()
    p = imgui.get_cursor_screen_pos()
    dl.add_rect_filled(p, imgui.ImVec2(p.x + width, p.y + height), col(LINE), 2.0)
    dl.add_rect_filled(p, imgui.ImVec2(p.x + width * max(0.0, min(1.0, frac)), p.y + height), col(tone), 2.0)
    imgui.dummy(imgui.ImVec2(width, height))


def eyebrow(text: str) -> None:
    if S.font_mono:
        imgui.push_font(S.font_mono, 11.0)
    imgui.text_colored(v4(TEXT_DIM), text.upper())
    if S.font_mono:
        imgui.pop_font()


def wrapped(text: str, color=None) -> None:
    if color is not None:
        imgui.push_style_color(imgui.Col_.text, v4(color))
    imgui.push_text_wrap_pos(0.0)
    imgui.text_unformatted(text)
    imgui.pop_text_wrap_pos()
    if color is not None:
        imgui.pop_style_color()


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


# ---------------------------------------------------------------- panels
def gui_hud() -> None:
    run = S.run
    t = ease((time.time() - S.hud_t0) / 0.9)
    imgui.push_style_var(imgui.StyleVar_.item_spacing, imgui.ImVec2(14, 4))

    # agent switcher
    for i, r in enumerate(S.runs):
        active = i == S.run_ix
        if S.font_mono:
            imgui.push_font(S.font_mono, 14.0)
        imgui.push_style_color(imgui.Col_.text, v4(ACCENT if active else TEXT_DIM))
        if imgui.selectable(r.label, active, imgui.SelectableFlags_.none, imgui.ImVec2(210, 0))[0]:
            S.select_run(i)
        imgui.pop_style_color()
        if S.font_mono:
            imgui.pop_font()
        if active:
            dl = imgui.get_window_draw_list()
            mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            dl.add_line(imgui.ImVec2(mn.x, mx.y + 1), imgui.ImVec2(mx.x, mx.y + 1), col(ACCENT), 2.0)
        imgui.same_line()

    imgui.same_line(0, 40)

    def stat(label: str, value: str, tone=TEXT) -> None:
        imgui.begin_group()
        eyebrow(label)
        if S.font_big:
            imgui.push_font(S.font_big, 20.0)
        imgui.text_colored(v4(tone), value)
        if S.font_big:
            imgui.pop_font()
        imgui.end_group()
        imgui.same_line()

    u = run.usage
    stat("model", run.model)
    stat("route", run.endpoint)
    stat("retention", run.retention, WARN if "unverified" in run.retention else OK)
    stat("data class", run.data_class.upper(), OK)
    stat("calls", f"{int(u['calls'] * t):d}")
    stat("tokens in / out", f"{int(u['in'] * t):,} / {int(u['out'] * t):,}")
    stat("cost", f"${u['usd'] * t:0.2f}")
    esc = sum(1 for d in run.docs if d.status == "escalated")
    stat("escalated", f"{int(esc * t)} / {len(run.docs)}", BAD if esc else OK)
    imgui.pop_style_var()


def gui_matter() -> None:
    run = S.run
    eyebrow(f"run {run.run_id} · {len(run.docs)} documents")
    imgui.separator()
    for i, d in enumerate(run.docs):
        active = i == S.doc_ix
        imgui.push_id(i)
        p = imgui.get_cursor_screen_pos()
        w = imgui.get_content_region_avail().x
        h = 46.0
        dl = imgui.get_window_draw_list()
        if active:
            dl.add_rect_filled(p, imgui.ImVec2(p.x + w, p.y + h), col(PANEL_2), 4.0)
            dl.add_rect_filled(p, imgui.ImVec2(p.x + 3, p.y + h), col(ACCENT), 2.0)
        if imgui.invisible_button("row", imgui.ImVec2(w, h)):
            S.select_doc(i)
        if imgui.is_item_hovered() and not active:
            dl.add_rect_filled(p, imgui.ImVec2(p.x + w, p.y + h), col(PANEL_2, 0.6), 4.0)
        # overlay text
        if S.font_mono:
            imgui.push_font(S.font_mono, 13.0)
        dl.add_text(imgui.ImVec2(p.x + 12, p.y + 7), col(TEXT), d.doc_id)
        if S.font_mono:
            imgui.pop_font()
        tone = BAD if d.status == "escalated" else TEXT_DIM
        dl.add_text(imgui.ImVec2(p.x + 12, p.y + 26), col(tone), d.headline)
        if d.status == "escalated":
            dl.add_circle_filled(imgui.ImVec2(p.x + w - 14, p.y + 14), 4.0, col(BAD))
        imgui.pop_id()
    imgui.dummy(imgui.ImVec2(0, 8))
    imgui.separator()
    eyebrow("keys")
    imgui.text_colored(v4(TEXT_DIM), "up / down  findings     enter  accept     backspace  send back")


def gui_document() -> None:
    doc = S.doc
    if S.font_doc:
        imgui.push_font(S.font_doc, 16.0)
    avail = imgui.get_content_region_avail()
    imgui.begin_child("docscroll", imgui.ImVec2(0, 0), imgui.ChildFlags_.none)
    margin = 28.0
    width = max(200.0, min(720.0, avail.x - margin * 2))
    lay = get_layout(doc, width)
    line_h = imgui.get_text_line_height() * 1.55
    dl = imgui.get_window_draw_list()
    origin = imgui.get_cursor_screen_pos()
    x0 = origin.x + margin
    spans = doc.spans
    # jump
    if S.jump_to:
        target = next((s for s in spans if s.key == S.jump_to), None)
        if target:
            for li, (a, b) in enumerate(lay.lines):
                if a <= target.start <= b:
                    imgui.set_scroll_y(max(0.0, li * line_h - imgui.get_window_height() * 0.4))
                    break
        S.jump_to = None

    clipper = imgui.ListClipper()
    clipper.begin(len(lay.lines), line_h)
    hovered_key = None
    while clipper.step():
        for li in range(clipper.display_start, clipper.display_end):
            a, b = lay.lines[li]
            y = origin.y + li * line_h
            line = doc.text[a:b]
            # highlights on this line
            for s in spans:
                if s.end <= a or s.start >= b:
                    continue
                hs, he = max(s.start, a), min(s.end, b)
                px0 = x0 + imgui.calc_text_size(doc.text[a:hs]).x
                px1 = x0 + imgui.calc_text_size(doc.text[a:he]).x
                tone = TONE[s.tone]
                sel = s.key == S.selected
                r0, r1 = imgui.ImVec2(px0 - 2, y - 2), imgui.ImVec2(px1 + 2, y + line_h - 6)
                dl.add_rect_filled(r0, r1, col(tone, 0.34 if sel else 0.18), 3.0)
                if sel:
                    dl.add_rect(r0, r1, col(tone, 0.9), 3.0, thickness=1.5)
                if imgui.is_mouse_hovering_rect(r0, r1):
                    hovered_key = s.key
                    dl.add_rect(r0, r1, col(ACCENT, 0.8), 3.0, thickness=1.0)
            dl.add_text(imgui.ImVec2(x0, y), col(TEXT), line)
    clipper.end()
    imgui.dummy(imgui.ImVec2(width + margin * 2, len(lay.lines) * line_h + 40))
    if hovered_key and imgui.is_mouse_clicked(0):
        S.selected = hovered_key
    imgui.end_child()
    if S.font_doc:
        imgui.pop_font()


def _finding_row(doc: Doc, f: Finding, selected: bool) -> None:
    tone = TONE[f.tone]
    imgui.push_id(f.key)
    p = imgui.get_cursor_screen_pos()
    w = imgui.get_content_region_avail().x
    dl = imgui.get_window_draw_list()
    imgui.begin_group()
    imgui.dummy(imgui.ImVec2(0, 4))
    imgui.indent(10)
    # title row
    if S.font_mono and doc.agent == "cite":
        imgui.push_font(S.font_mono, 14.0)
    imgui.text_colored(v4(TEXT), f.title)
    if S.font_mono and doc.agent == "cite":
        imgui.pop_font()
    imgui.same_line(w - 150)
    if S.font_mono:
        imgui.push_font(S.font_mono, 12.0)
    imgui.text_colored(v4(TEXT_DIM), f"{f.confidence * 100:3.0f}%" if doc.agent == "nda" else (f"p.{f.page}" if f.page else ""))
    if S.font_mono:
        imgui.pop_font()
    imgui.same_line(w - 100)
    badge(f.verdict, tone)
    # body
    if f.value and f.value != "—":
        wrapped(f.value)
    if f.quote and doc.agent == "nda":
        if S.font_doc:
            imgui.push_font(S.font_doc, 13.0)
        wrapped("“" + f.quote + "”", TEXT_DIM)
        if S.font_doc:
            imgui.pop_font()
    if f.quote and doc.agent == "cite":
        wrapped("database: " + f.quote, TEXT_DIM)
    if f.detail:
        wrapped(f.detail, BAD if f.tone == "bad" else TEXT_DIM)
    if doc.agent == "nda":
        meter(f.confidence, tone, w - 30)
    if selected:
        imgui.dummy(imgui.ImVec2(0, 2))
        dkey = f"{doc.doc_id}:{f.key}"
        cur = S.decisions.get(dkey)
        imgui.push_style_color(imgui.Col_.button, v4(OK if cur == "accepted" else PANEL_2))
        if imgui.button("ACCEPT", imgui.ImVec2(90, 24)):
            S.decisions[dkey] = None if cur == "accepted" else "accepted"
        imgui.pop_style_color()
        imgui.same_line()
        imgui.push_style_color(imgui.Col_.button, v4(BAD if cur == "sent_back" else PANEL_2))
        if imgui.button("SEND BACK", imgui.ImVec2(100, 24)):
            S.decisions[dkey] = None if cur == "sent_back" else "sent_back"
        imgui.pop_style_color()
        if f.url:
            imgui.same_line()
            imgui.text_colored(v4(TEXT_DIM), "courtlistener.com" + f.url[:38] + ("…" if len(f.url) > 38 else ""))
    imgui.unindent(10)
    imgui.dummy(imgui.ImVec2(0, 6))
    imgui.end_group()
    mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    if selected:
        dl.add_rect_filled(imgui.ImVec2(p.x, mn.y), imgui.ImVec2(p.x + w, mx.y), col(PANEL_2, 0.7), 4.0)
        dl.add_rect_filled(imgui.ImVec2(p.x, mn.y), imgui.ImVec2(p.x + 3, mx.y), col(tone), 2.0)
    elif imgui.is_mouse_hovering_rect(imgui.ImVec2(p.x, mn.y), imgui.ImVec2(p.x + w, mx.y)):
        dl.add_rect_filled(imgui.ImVec2(p.x, mn.y), imgui.ImVec2(p.x + w, mx.y), col(PANEL_2, 0.35), 4.0)
        if imgui.is_mouse_clicked(0):
            S.select(f.key)
    dl.add_line(imgui.ImVec2(p.x, mx.y + 1), imgui.ImVec2(p.x + w, mx.y + 1), col(LINE, 0.6))
    imgui.pop_id()


def gui_findings() -> None:
    doc = S.doc
    fs = doc.findings
    # summary strip
    if doc.agent == "nda":
        found = sum(1 for f in fs if f.verdict == "Found")
        located = len(doc.spans)
        cells = [("terms found", f"{found} / 12", TEXT), ("quotes located", f"{located} / {found}", OK if located == found else WARN)]
    else:
        res = sum(1 for f in fs if f.verdict == "Resolved")
        human = sum(1 for f in fs if f.tone in ("bad", "warn", "dim") and f.verdict != "Skipped")
        cells = [("citations", str(len(fs)), TEXT), ("resolved", str(res), OK), ("need a human", str(human), BAD if human else OK)]
    for label, value, tone in cells:
        imgui.begin_group()
        eyebrow(label)
        if S.font_big:
            imgui.push_font(S.font_big, 20.0)
        imgui.text_colored(v4(tone), value)
        if S.font_big:
            imgui.pop_font()
        imgui.end_group()
        imgui.same_line(0, 28)
    imgui.new_line()
    if doc.status == "escalated":
        p = imgui.get_cursor_screen_pos()
        w = imgui.get_content_region_avail().x
        dl = imgui.get_window_draw_list()
        imgui.begin_group()
        imgui.indent(10)
        imgui.dummy(imgui.ImVec2(0, 6))
        imgui.text_colored(v4(BAD), "ESCALATED TO THE NAMED REVIEWER")
        for r in doc.reasons:
            wrapped("· " + r, TEXT)
        if doc.injection:
            wrapped("The document addresses the model directly. Flagged before extraction; the model's answers were not trusted.", TEXT_DIM)
        imgui.dummy(imgui.ImVec2(0, 6))
        imgui.unindent(10)
        imgui.end_group()
        mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        dl.add_rect_filled(imgui.ImVec2(p.x, mn.y), imgui.ImVec2(p.x + w, mx.y), col(BAD, 0.10), 4.0)
        dl.add_rect(imgui.ImVec2(p.x, mn.y), imgui.ImVec2(p.x + w, mx.y), col(BAD, 0.5), 4.0)
        imgui.dummy(imgui.ImVec2(0, 6))
    imgui.separator()
    imgui.begin_child("findscroll", imgui.ImVec2(0, 0))
    # keyboard
    keys = [f.key for f in fs if (doc.agent == "cite" or f.verdict != "Not in document")]
    if keys and imgui.is_window_focused(imgui.FocusedFlags_.root_and_child_windows):
        ix = keys.index(S.selected) if S.selected in keys else -1
        if imgui.is_key_pressed(imgui.Key.down_arrow):
            S.select(keys[min(len(keys) - 1, ix + 1)])
        if imgui.is_key_pressed(imgui.Key.up_arrow):
            S.select(keys[max(0, ix - 1)])
        if S.selected and imgui.is_key_pressed(imgui.Key.enter):
            S.decisions[f"{doc.doc_id}:{S.selected}"] = "accepted"
        if S.selected and imgui.is_key_pressed(imgui.Key.backspace):
            S.decisions[f"{doc.doc_id}:{S.selected}"] = "sent_back"
    for f in fs:
        _finding_row(doc, f, f.key == S.selected)
    imgui.end_child()


def gui_trace() -> None:
    run = S.run
    n = len(run.egress)
    doc_bytes = sum(1 for e in run.egress if e.get("contains_document"))
    eyebrow(f"egress log · {n} requests left this machine · {doc_bytes} carried document text")
    if n == 0:
        imgui.text_colored(v4(OK), "No network call in this run. Replayed from the local cache.")
    imgui.separator()
    if S.font_mono:
        imgui.push_font(S.font_mono, 12.0)
    if imgui.begin_table("egress", 7, imgui.TableFlags_.row_bg | imgui.TableFlags_.scroll_y | imgui.TableFlags_.sizing_stretch_prop):
        for h, wgt in (("time", 1.3), ("host", 1.2), ("path", 0.8), ("bytes", 0.6), ("doc text", 0.7), ("status", 0.5), ("note", 2.5)):
            imgui.table_setup_column(h, imgui.TableColumnFlags_.width_stretch, wgt)
        imgui.table_setup_scroll_freeze(0, 1)
        imgui.table_headers_row()
        for e in run.egress[-300:]:
            imgui.table_next_row()
            imgui.table_next_column(); imgui.text_colored(v4(TEXT_DIM), str(e.get("at", ""))[11:19])
            imgui.table_next_column(); imgui.text(str(e.get("host", "")))
            imgui.table_next_column(); imgui.text(str(e.get("path", "")))
            imgui.table_next_column(); imgui.text(f"{e.get('body_bytes', 0):,}")
            imgui.table_next_column()
            if e.get("contains_document"):
                imgui.text_colored(v4(WARN), "yes")
            else:
                imgui.text_colored(v4(OK), "no")
            imgui.table_next_column()
            st = e.get("status", 0)
            imgui.text_colored(v4(OK if st == 200 else BAD), str(st))
            imgui.table_next_column(); imgui.text_colored(v4(TEXT_DIM), str(e.get("note", ""))[:60])
        imgui.end_table()
    if S.font_mono:
        imgui.pop_font()


def _graph_for(run: Run) -> G.Graph | None:
    if run.agent != "cite" or run.run_dir is None:
        return None
    g = S.graphs.get(run.run_id)
    if g is None:
        g = G.build(run.run_dir)
        S.graphs[run.run_id] = g
    return g


def gui_graph() -> None:
    run = S.run
    g = _graph_for(run)
    if g is None:
        imgui.text_colored(v4(TEXT_DIM), "The citation graph is drawn from a citation-verifier run. Switch to 002 in the HUD.")
        return

    # header strip
    n_brief = sum(1 for n in g.nodes if n.kind == "brief")
    n_case = len(g.nodes) - n_brief
    n_flag = sum(1 for n in g.nodes if n.flagged)
    eyebrow(f"{n_brief} briefs · {n_case} authorities cited by two or more briefs or flagged ({n_flag} flagged) · {len(g.edges)} citations")
    imgui.same_line(0, 24)
    if imgui.small_button("SHAKE"):
        g.heat = 1.0
        g.user_moved = False
    imgui.same_line(0, 12)
    if imgui.small_button("FIT"):
        g.user_moved = False
    imgui.new_line()
    for label, tone in (("brief", ACCENT), ("resolved", OK), ("unresolved", WARN), ("name mismatch", BAD), ("not checked", DIM)):
        dl = imgui.get_window_draw_list()
        p = imgui.get_cursor_screen_pos()
        dl.add_circle_filled(imgui.ImVec2(p.x + 6, p.y + 8), 4.5, col(tone))
        imgui.dummy(imgui.ImVec2(14, 14))
        imgui.same_line(0, 2)
        imgui.text_colored(v4(TEXT_DIM), label)
        imgui.same_line(0, 14)
    imgui.new_line()

    # canvas
    avail = imgui.get_content_region_avail()
    origin = imgui.get_cursor_screen_pos()
    size = imgui.ImVec2(max(50.0, avail.x), max(50.0, avail.y))
    dl = imgui.get_window_draw_list()
    dl.add_rect_filled(origin, imgui.ImVec2(origin.x + size.x, origin.y + size.y), col(BG))
    dl.push_clip_rect(origin, imgui.ImVec2(origin.x + size.x, origin.y + size.y), True)
    imgui.invisible_button("graphcanvas", size)
    hovered_canvas = imgui.is_item_hovered()
    io = imgui.get_io()
    cx, cy = origin.x + size.x / 2 + g.pan[0], origin.y + size.y / 2 + g.pan[1]

    def to_screen(i: int) -> tuple[float, float]:
        return cx + g.pos[i, 0] * g.zoom, cy + g.pos[i, 1] * g.zoom

    # interaction
    mouse = io.mouse_pos
    if not g.user_moved:
        G.fit(g, size.x, size.y)
        cx, cy = origin.x + size.x / 2 + g.pan[0], origin.y + size.y / 2 + g.pan[1]
    if hovered_canvas and io.mouse_wheel != 0.0:
        g.user_moved = True
        old = g.zoom
        g.zoom = max(0.25, min(4.0, g.zoom * (1.12 if io.mouse_wheel > 0 else 1 / 1.12)))
        # zoom around the cursor
        g.pan = (g.pan[0] + (mouse.x - cx) * (1 - g.zoom / old), g.pan[1] + (mouse.y - cy) * (1 - g.zoom / old))
        cx, cy = origin.x + size.x / 2 + g.pan[0], origin.y + size.y / 2 + g.pan[1]
    g.hover = None
    if hovered_canvas:
        best, best_d = None, 1e9
        for i, nd in enumerate(g.nodes):
            sx, sy = to_screen(i)
            r = (9.0 if nd.kind == "brief" else 3.5 + 1.2 * nd.degree ** 0.5) * g.zoom ** 0.5
            d2 = (mouse.x - sx) ** 2 + (mouse.y - sy) ** 2
            if d2 < (r + 5) ** 2 and d2 < best_d:
                best, best_d = i, d2
        g.hover = best
    if imgui.is_mouse_clicked(0) and hovered_canvas:
        g.drag_node = g.hover
        if g.hover is not None:
            g.heat = max(g.heat, 0.3)
    if imgui.is_mouse_down(0) and imgui.is_item_active():
        d = io.mouse_delta
        if g.drag_node is not None:
            g.pos[g.drag_node] += np.array([d.x, d.y]) / g.zoom
        elif d.x or d.y:
            g.user_moved = True
            g.pan = (g.pan[0] + d.x, g.pan[1] + d.y)
    if imgui.is_mouse_released(0):
        if g.drag_node is not None and io.mouse_delta.x == 0 and io.mouse_delta.y == 0:
            _graph_click(g, g.drag_node)
        g.drag_node = None

    G.step(g)

    # edges
    for e in g.edges:
        ax, ay = to_screen(e.a)
        bx, by = to_screen(e.b)
        lit = g.hover in (e.a, e.b)
        tone = TONE[e.tone]
        dl.add_line(imgui.ImVec2(ax, ay), imgui.ImVec2(bx, by), col(tone, 0.85 if lit else (0.28 if e.tone != "dim" else 0.12)),
                    2.0 if lit else 1.0)
    # nodes
    for i, nd in enumerate(g.nodes):
        sx, sy = to_screen(i)
        if nd.kind == "brief":
            r = 9.0 * g.zoom ** 0.5
            dl.add_circle_filled(imgui.ImVec2(sx, sy), r, col(ACCENT, 0.18))
            dl.add_circle(imgui.ImVec2(sx, sy), r, col(ACCENT), 0, 1.5)
            if any(d.doc_id == nd.id for d in run.docs):
                dl.add_circle_filled(imgui.ImVec2(sx, sy), 3.0, col(ACCENT))
        else:
            r = (3.5 + 1.2 * nd.degree ** 0.5) * g.zoom ** 0.5
            tone = TONE[nd.tone]
            dl.add_circle_filled(imgui.ImVec2(sx, sy), r, col(tone, 0.9 if nd.flagged else 0.7))
            if nd.flagged:
                pulse = 0.5 + 0.5 * np.sin(time.time() * 3.0)
                dl.add_circle(imgui.ImVec2(sx, sy), r + 3 + 3 * pulse, col(tone, 0.5 * (1 - pulse)), 0, 1.5)
        if i == g.hover:
            dl.add_circle(imgui.ImVec2(sx, sy), (12.0 if nd.kind == "brief" else 8.0) * g.zoom ** 0.5, col(TEXT), 0, 1.5)
    # labels
    if S.font_mono:
        imgui.push_font(S.font_mono, 11.0)
    for i, nd in enumerate(g.nodes):
        show = nd.kind == "brief" or nd.flagged or nd.degree >= 3 or g.zoom > 1.6 or i == g.hover
        if not show:
            continue
        sx, sy = to_screen(i)
        tone = ACCENT if nd.kind == "brief" else TONE[nd.tone]
        dl.add_text(imgui.ImVec2(sx + 10, sy - 7), col(tone, 0.95 if (nd.kind == "brief" or nd.flagged or i == g.hover) else 0.6), nd.label)
    if S.font_mono:
        imgui.pop_font()
    dl.pop_clip_rect()

    # tooltip
    if g.hover is not None:
        nd = g.nodes[g.hover]
        imgui.begin_tooltip()
        if S.font_mono:
            imgui.push_font(S.font_mono, 13.0)
        imgui.text_colored(v4(ACCENT if nd.kind == "brief" else TONE[nd.tone]), nd.id if nd.kind == "brief" else nd.label)
        if S.font_mono:
            imgui.pop_font()
        if nd.sub:
            imgui.text_colored(v4(TEXT), nd.sub)
        imgui.separator()
        for e in g.edges:
            if nd.kind == "case" and e.b == g.hover:
                imgui.text_colored(v4(TONE[e.tone]), f"{e.verdict:14}")
                imgui.same_line()
                imgui.text_colored(v4(TEXT_DIM), f"{g.nodes[e.a].label}  as written: {e.written[:48]}")
            elif nd.kind == "brief" and e.a == g.hover and e.tone != "ok":
                imgui.text_colored(v4(TONE[e.tone]), f"{e.verdict:14}")
                imgui.same_line()
                imgui.text_colored(v4(TEXT_DIM), g.nodes[e.b].label)
        if nd.kind == "brief":
            imgui.text_colored(v4(TEXT_DIM), f"{nd.degree} shared or flagged authorities · click to open")
        else:
            imgui.text_colored(v4(TEXT_DIM), f"cited by {nd.degree} brief(s) · click to open a citing brief")
        imgui.end_tooltip()


def _graph_click(g: G.Graph, i: int) -> None:
    """Open the brief in DOCUMENT / FINDINGS and select the citation if that brief is loaded."""
    nd = g.nodes[i]
    run = S.run
    if nd.kind == "brief":
        for ix, d in enumerate(run.docs):
            if d.doc_id == nd.id:
                S.select_doc(ix)
                return
        return
    for e in g.edges:
        if e.b != i:
            continue
        brief_id = g.nodes[e.a].id
        for ix, d in enumerate(run.docs):
            if d.doc_id == brief_id:
                S.select_doc(ix)
                S.select(e.key)
                return


def gui_status() -> None:
    imgui.text_colored(v4(TEXT_DIM), "No item on this screen is final. A named human decides each one.   ·   Public and synthetic documents only.")


# ---------------------------------------------------------------- app
def setup_style() -> None:
    st = imgui.get_style()
    st.window_rounding = 0.0
    st.frame_rounding = 3.0
    st.child_rounding = 0.0
    st.window_padding = imgui.ImVec2(12, 10)
    st.frame_padding = imgui.ImVec2(8, 4)
    st.item_spacing = imgui.ImVec2(8, 5)
    st.window_border_size = 0.0
    st.scrollbar_size = 10.0
    st.scrollbar_rounding = 4.0
    c = imgui.Col_
    for idx, colour in (
        (c.window_bg, PANEL), (c.child_bg, PANEL), (c.popup_bg, PANEL_2), (c.border, LINE),
        (c.frame_bg, PANEL_2), (c.frame_bg_hovered, LINE), (c.frame_bg_active, LINE),
        (c.title_bg, BG), (c.title_bg_active, BG), (c.title_bg_collapsed, BG), (c.menu_bar_bg, BG),
        (c.scrollbar_bg, PANEL), (c.scrollbar_grab, LINE), (c.scrollbar_grab_hovered, DIM), (c.scrollbar_grab_active, ACCENT),
        (c.button, PANEL_2), (c.button_hovered, LINE), (c.button_active, ACCENT),
        (c.header, PANEL_2), (c.header_hovered, LINE), (c.header_active, LINE),
        (c.separator, LINE), (c.tab, BG), (c.tab_hovered, PANEL_2), (c.tab_selected, PANEL), (c.tab_dimmed, BG), (c.tab_dimmed_selected, PANEL),
        (c.docking_preview, ACCENT), (c.docking_empty_bg, BG), (c.text, TEXT), (c.text_disabled, TEXT_DIM),
        (c.table_header_bg, PANEL_2), (c.table_row_bg, PANEL), (c.table_row_bg_alt, PANEL_2), (c.table_border_light, LINE), (c.table_border_strong, LINE),
        (c.plot_histogram, ACCENT), (c.check_mark, ACCENT), (c.nav_cursor, ACCENT),
    ):
        st.set_color_(idx, v4(colour))


def load_fonts() -> None:
    S.font_ui = hello_imgui.load_font("fonts/Roboto/Roboto-Regular.ttf", 15.0)
    S.font_mono = hello_imgui.load_font("fonts/Inconsolata-Medium.ttf", 13.0)
    S.font_doc = hello_imgui.load_font("fonts/DroidSans.ttf", 16.0)
    S.font_big = hello_imgui.load_font("fonts/Roboto/Roboto-Bold.ttf", 20.0)


def before_render() -> None:
    S.frames += 1
    if S.smoke and S.frames > 90:
        hello_imgui.get_runner_params().app_shall_exit = True


def main() -> None:
    global S
    runs = load_runs()
    if not runs:
        sys.exit("no runs found under runs/; run an agent first")
    S = State(runs=runs, smoke="--smoke" in sys.argv or "--smoke-graph" in sys.argv, hud_t0=time.time(),
              focus_graph="--smoke-graph" in sys.argv)
    if S.focus_graph:
        S.run_ix = next((i for i, r in enumerate(runs) if r.agent == "cite"), 0)

    rp = hello_imgui.RunnerParams()
    rp.app_window_params.window_title = "Legal Agents · desk"
    rp.app_window_params.window_geometry.size = (1680, 1020)
    rp.app_window_params.restore_previous_geometry = False
    rp.imgui_window_params.default_imgui_window_type = hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
    rp.imgui_window_params.enable_viewports = False
    rp.imgui_window_params.show_status_bar = True
    rp.callbacks.show_status = gui_status
    rp.callbacks.setup_imgui_style = setup_style
    rp.callbacks.load_additional_fonts = load_fonts
    rp.callbacks.before_imgui_render = before_render
    rp.fps_idling.enable_idling = False

    rp.docking_params.docking_splits = [
        hello_imgui.DockingSplit("MainDockSpace", "HudSpace", imgui.Dir.up, 0.085),
        hello_imgui.DockingSplit("MainDockSpace", "TraceSpace", imgui.Dir.down, 0.22),
        hello_imgui.DockingSplit("MainDockSpace", "MatterSpace", imgui.Dir.left, 0.20),
        hello_imgui.DockingSplit("MainDockSpace", "FindingsSpace", imgui.Dir.right, 0.36),
    ]
    windows = []
    for label, space, fn in (
        ("HUD", "HudSpace", gui_hud),
        ("MATTER", "MatterSpace", gui_matter),
        ("DOCUMENT", "MainDockSpace", gui_document),
        ("GRAPH", "MainDockSpace", gui_graph),
        ("FINDINGS", "FindingsSpace", gui_findings),
        ("TRACE", "TraceSpace", gui_trace),
    ):
        w = hello_imgui.DockableWindow(label, space, fn)
        w.can_be_closed = False
        if label == "GRAPH" and S.focus_graph:
            w.focus_window_at_next_frame = True
        windows.append(w)
    rp.docking_params.dockable_windows = windows
    rp.docking_params.main_dock_space_node_flags = imgui.DockNodeFlags_.none
    hello_imgui.run(rp)
    if S.smoke:
        _save_png(hello_imgui.final_app_window_screenshot(), ROOT_RUNS / "desk-smoke.png")
        print(f"smoke ok: {S.frames} frames; screenshot at runs/desk-smoke.png")


def _save_png(img, path) -> None:
    """Pure-Python PNG writer (no PIL dependency) for the smoke screenshot."""
    import struct
    import zlib

    import numpy as np

    arr = np.asarray(img)
    h, w = arr.shape[0], arr.shape[1]
    rgb = arr[:, :, :3] if arr.ndim == 3 else np.stack([arr] * 3, axis=-1)
    raw = b"".join(b"\x00" + rgb[y].astype(np.uint8).tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    path.write_bytes(png)


if __name__ == "__main__":
    main()
