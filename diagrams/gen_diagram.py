"""Generate the multi-agent architecture diagram as .excalidraw (editable) and .svg (preview)."""
import json, os, random, html

random.seed(7)
OUT = os.path.dirname(os.path.abspath(__file__)) + "/"

# palette: (stroke, fill)
AGENT = ("#1971c2", "#d0ebff")      # LLM agent
CODE = ("#2f9e44", "#d3f9d8")       # deterministic code
HUMAN = ("#c2255c", "#ffdeeb")      # human action
STORE = ("#495057", "#e9ecef")      # data store
SKILL = ("#7048e8", "#e5dbff")      # skill
ORCH = ("#e67700", "#fff3bf")       # orchestrator
GATE = ("#e03131", "#ffe3e3")       # the hard gate
FAIL = ("#868e96", "#f8f9fa")

els = []          # excalidraw elements
svg = []          # svg fragments
boxes = {}

def nid():
    return "e%08x" % random.getrandbits(32)

def base(t, x, y, w, h, stroke, fill, dashed=False, sw=2):
    return {"id": nid(), "type": t, "x": x, "y": y, "width": w, "height": h, "angle": 0,
            "strokeColor": stroke, "backgroundColor": fill, "fillStyle": "solid",
            "strokeWidth": sw, "strokeStyle": "dashed" if dashed else "solid", "roughness": 1,
            "opacity": 100, "groupIds": [], "frameId": None,
            "roundness": {"type": 3} if t == "rectangle" else None,
            "seed": random.randint(1, 2**31), "version": 1, "versionNonce": random.randint(1, 2**31),
            "isDeleted": False, "boundElements": [], "updated": 1, "link": None, "locked": False}

def text_el(x, y, w, h, txt, size, color="#1e1e1e", align="center", container=None, valign="middle"):
    e = base("text", x, y, w, h, color, "transparent")
    e.update({"text": txt, "fontSize": size, "fontFamily": 2, "textAlign": align,
              "verticalAlign": valign, "containerId": container, "originalText": txt,
              "lineHeight": 1.25, "autoResize": True})
    e["roundness"] = None
    return e

def svg_text(x, y, w, h, txt, size, color, align="center", bold_first=False, valign="middle"):
    lines = txt.split("\n")
    lh = size * 1.3
    total = lh * len(lines)
    y0 = y + (h - total) / 2 + size if valign == "middle" else y + size
    anchor = {"center": "middle", "left": "start"}[align]
    tx = x + w / 2 if align == "center" else x + 10
    out = []
    for i, ln in enumerate(lines):
        weight = "bold" if (bold_first and i == 0) else "normal"
        out.append(f'<text x="{tx}" y="{y0 + i*lh:.1f}" font-size="{size}" fill="{color}" '
                   f'text-anchor="{anchor}" font-weight="{weight}">{html.escape(ln)}</text>')
    return "\n".join(out)

def box(key, x, y, w, h, txt, pal, size=15, dashed=False, align="center", sw=2, title_bold=True):
    r = base("rectangle", x, y, w, h, pal[0], pal[1], dashed, sw)
    t = text_el(x + 6, y + 6, w - 12, h - 12, txt, size, align=align, container=r["id"])
    r["boundElements"].append({"type": "text", "id": t["id"]})
    els.extend([r, t])
    boxes[key] = (r, x, y, w, h)
    dash = ' stroke-dasharray="8 6"' if dashed else ""
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{pal[1]}" '
               f'stroke="{pal[0]}" stroke-width="{sw}"{dash}/>')
    svg.append(svg_text(x, y, w, h, txt, size, "#1e1e1e", align, title_bold))

def frame(x, y, w, h, label, color):
    r = base("rectangle", x, y, w, h, color, "transparent", True, 2)
    els.append(r)
    t = text_el(x + 14, y + 10, w - 28, 24, label, 18, color, "left", valign="top")
    els.append(t)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="none" '
               f'stroke="{color}" stroke-width="2" stroke-dasharray="10 7"/>')
    svg.append(f'<text x="{x+16}" y="{y+30}" font-size="18" font-weight="bold" fill="{color}">{html.escape(label)}</text>')

def label(x, y, txt, size=13, color="#495057", w=None):
    w = w or max(len(l) for l in txt.split("\n")) * size * 0.56
    h = len(txt.split("\n")) * size * 1.3
    els.append(text_el(x, y, w, h, txt, size, color, "left", valign="top"))
    for i, ln in enumerate(txt.split("\n")):
        svg.append(f'<text x="{x}" y="{y + size + i*size*1.3:.1f}" font-size="{size}" fill="{color}" '
                   f'font-style="italic">{html.escape(ln)}</text>')

def anchor(key, side):
    _, x, y, w, h = boxes[key]
    if ":" in side:
        sd, v = side.split(":"); v = float(v)
        return {"t": (v, y), "b": (v, y + h), "l": (x, v), "r": (x + w, v)}[sd]
    return {"l": (x, y + h/2), "r": (x + w, y + h/2), "t": (x + w/2, y), "b": (x + w/2, y + h)}[side]

def arrow(a, b, via=(), color="#343a40", dashed=False, txt=None, txt_at=None, both=False):
    (ka, sa), (kb, sb) = a, b
    p0, p1 = anchor(ka, sa), anchor(kb, sb)
    pts = [p0, *via, p1]
    e = base("arrow", p0[0], p0[1], 0, 0, color, "transparent", dashed, 2)
    rel = [[px - p0[0], py - p0[1]] for px, py in pts]
    xs, ys = [p[0] for p in rel], [p[1] for p in rel]
    e.update({"points": rel, "width": max(xs) - min(xs), "height": max(ys) - min(ys),
              "lastCommittedPoint": None,
              "startBinding": {"elementId": boxes[ka][0]["id"], "focus": 0, "gap": 4},
              "endBinding": {"elementId": boxes[kb][0]["id"], "focus": 0, "gap": 4},
              "startArrowhead": "arrow" if both else None, "endArrowhead": "arrow",
              "elbowed": False})
    e["roundness"] = {"type": 2} if not via else None
    boxes[ka][0]["boundElements"].append({"type": "arrow", "id": e["id"]})
    boxes[kb][0]["boundElements"].append({"type": "arrow", "id": e["id"]})
    els.append(e)
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    mk = f'marker-end="url(#ah-{color[1:]})"' + (f' marker-start="url(#ahs-{color[1:]})"' if both else "")
    path = " ".join(f"{px},{py}" for px, py in pts)
    svg.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2"{dash}/>')
    def head(tip, frm):
        import math
        a = math.atan2(tip[1] - frm[1], tip[0] - frm[0]); L, s_ = 12, 0.45
        p2 = (tip[0] - L*math.cos(a - s_), tip[1] - L*math.sin(a - s_))
        p3 = (tip[0] - L*math.cos(a + s_), tip[1] - L*math.sin(a + s_))
        svg.append(f'<polygon points="{tip[0]},{tip[1]} {p2[0]:.1f},{p2[1]:.1f} {p3[0]:.1f},{p3[1]:.1f}" fill="{color}"/>')
    head(pts[-1], pts[-2])
    if both:
        head(pts[0], pts[1])
    if txt:
        label(*(txt_at or ((p0[0]+p1[0])/2 + 6, (p0[1]+p1[1])/2 - 18)), txt)

# ---------------------------------------------------------------- layout
W, H = 1900, 1230
title = "Verified Content Engine — multi-agent architecture"
els.append(text_el(40, 24, 900, 36, title, 28, "#1e1e1e", "left", valign="top"))
svg.append(f'<text x="40" y="54" font-size="28" font-weight="bold" fill="#1e1e1e">{title}</text>')
label(40, 66, "Orchestrator-worker, with sequential handoffs where steps depend on each other and parallel fan-out where they don't. Models propose; code decides.", 15, "#495057")

# people
box("people", 40, 130, 300, 130, "People (Web UI → API)\nmarketer · reviewer · SME\ncompliance · admin\nonly humans rule, override,\napprove, export", HUMAN, 14)

# ---- lane 1: ingestion
frame(380, 110, 1480, 350, "1 · INGESTION  —  parallel fan-out by source type", "#1971c2")
box("ingest", 410, 230, 200, 100, "ingest service (code)\nsnapshot · sha256\nmanifest · staleness", CODE, 14)
ys = [160, 230, 300, 370]
ex = [("cx", "claims-extractor\ntruth sources → cited claims"),
      ("sx", "style-extractor\nstyle sources → voice profile"),
      ("px", "positioning-extractor\npositioning + decisions → pack"),
      ("vx", "evidence-extractor (optional)\ncalls/surveys → market evidence")]
for (k, t), y in zip(ex, ys):
    box(k, 680, y, 270, 58, t, AGENT, 13)
box("reg", 1020, 230, 230, 100, "registry.build + validate\n(code)\nIDs · rulings · conflicts", CODE, 14)
box("kb", 1320, 160, 260, 200, "Knowledge base\n(per product, versioned)\n\n• claims registry\n• style profile + threshold\n• positioning pack\n• decisions log", STORE, 14, align="center")
box("sme", 1620, 230, 220, 110, "SME review queue\nconfirm · reject\ndeprioritize · doc-wrong\nrule on conflicts", HUMAN, 13)

arrow(("people", "r"), ("ingest", "l"), via=[(375, 195), (375, 280)], txt="upload /\nimport docs", txt_at=(250, 270))
for k in ["cx", "sx", "px", "vx"]:
    arrow(("ingest", "r"), (k, "l"), via=[(645, 280), (645, boxes[k][2] + 29)])
    arrow((k, "r"), ("reg", "l"), via=[(985, boxes[k][2] + 29), (985, 280)])
label(620, 432, "fan-out: one extractor per source type, one record per file, run in parallel", 13, "#1971c2")
arrow(("reg", "r"), ("kb", "l"))
arrow(("kb", "r"), ("sme", "l"), via=[(1600, 260), (1600, 285)], both=True, txt="needs-review ⇄ rulings", txt_at=(1625, 350))

# ---- lane 2: content run
frame(40, 490, 1820, 600, "2 · CONTENT RUN  —  orchestrator-worker · sequential handoffs · parallel verification", "#e67700")
box("orch", 300, 540, 1540, 52, "ORCHESTRATOR (code)  —  dispatches every step below · per-run budget · revision cap = 2 · retry once · resume from last step · calls gate code for every decision", ORCH, 14)
box("brief", 70, 620, 190, 90, "Brief (human)\ntype · audience\ngoal · stage", HUMAN, 14)
box("strat", 300, 630, 200, 80, "strategist\nplan · claims per section\nproof gaps", AGENT, 13)
box("copy", 560, 630, 200, 80, "copywriter\ntagged draft\n+ claim map", AGENT, 13)
vy = [615, 685, 755, 825]
vs = [("ver", "verifier — THE GATE\nper-sentence verdicts", GATE),
      ("sty", "style-checker\nscore vs threshold", AGENT),
      ("bpa", "best-practice-auditor\nstructure · positioning · stage", AGENT),
      ("buy", "synthetic-buyer (optional)\nreaction · objections", AGENT)]
for (k, t, p), y in zip(vs, vy):
    box(k, 840, y, 260, 58, t, p, 13, sw=3 if k == "ver" else 2)
box("comb", 1170, 690, 220, 100, "gate.combine (code)\nany block → Blocked\nhigh flag → Flagged\nelse → Approved", CODE, 13)
box("fin", 1470, 620, 220, 80, "gate.finalize (code)\nstrip tags → export\nApproved only", CODE, 13)
box("rev", 1470, 760, 370, 120, "Human review queue\nedit → re-verify · direct a revision\nadd a source (enters needs-review)\noverride (written reason → approved-override)\nreject", HUMAN, 13)

arrow(("people", "l"), ("brief", "l"), via=[(22, 195), (22, 665)])
arrow(("brief", "r"), ("strat", "l"))
arrow(("strat", "r"), ("copy", "l"), txt="plan", txt_at=(512, 645))
for k, _, _ in vs:
    arrow(("copy", "r"), (k, "l"), via=[(800, 670), (800, boxes[k][2] + 29)])
    arrow((k, "r"), ("comb", "l"), via=[(1135, boxes[k][2] + 29), (1135, 740)])
label(1145, 600, "fan-out: 4 independent reads\nof the same draft\njoin: wait for all, then combine", 13, "#e67700")
arrow(("comb", "r"), ("fin", "l"), via=[(1430, 740), (1430, 660)], txt="Approved", txt_at=(1395, 702), color="#2f9e44")
arrow(("comb", "r"), ("rev", "l"), via=[(1430, 740), (1430, 820)], txt="after 2 auto\nrounds", txt_at=(1395, 835), color="#c2255c")
arrow(("comb", "b"), ("copy", "b:710"), via=[(1280, 930), (710, 930)], color="#e03131", dashed=True,
      txt="Blocked / Flagged and rounds < 2 →\ncopywriter revises, whole page re-verified", txt_at=(722, 936))
arrow(("kb", "b"), ("orch", "t:1450"), dashed=True, color="#495057")
label(1462, 368, "read-only context slices\n(registry · profile · pack)", 13)

# skills
box("sk1", 300, 990, 460, 70, "skills: conversion-copywriter · copy frameworks\nshape structure & tone only — facts come from the registry", SKILL, 13)
box("sk2", 840, 990, 380, 70, "skills: positioning-auditor · awareness-scorer\nbuyer-persona (for synthetic-buyer)", SKILL, 13)
arrow(("sk1", "t:610"), ("copy", "b:610"), dashed=True, color="#7048e8")
arrow(("sk1", "t:400"), ("strat", "b"), dashed=True, color="#7048e8")
arrow(("sk2", "t:970"), ("buy", "b"), dashed=True, color="#7048e8")

box("fail", 1290, 960, 550, 115, "Failure handling\n• agent crash / stall → retry once → fail loud with context, resume later\n• schema-invalid output = failed step\n• budget reached → clean stop, partial run saved\n• failed revision of approved copy → last approved version stays live", FAIL, 13, align="left")

# legend
lx, ly = 40, 1120
items = [("LLM agent", AGENT), ("deterministic code", CODE), ("human action", HUMAN), ("data store", STORE),
         ("skill", SKILL), ("orchestrator", ORCH), ("hard gate", GATE)]
for i, (n, p) in enumerate(items):
    box(f"lg{i}", lx + i * 200, ly, 180, 40, n, p, 14)
label(1460, 1125, "solid arrow = handoff · dashed = context / loop", 13)

# ---------------------------------------------------------------- write
doc = {"type": "excalidraw", "version": 2, "source": "https://excalidraw.com",
       "elements": els, "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
       "files": {}}
with open(OUT + "multi-agent-architecture.excalidraw", "w") as f:
    json.dump(doc, f, indent=1)

colors = {"#343a40", "#2f9e44", "#c2255c", "#e03131", "#495057", "#7048e8"}
defs = "".join(
    f'<marker id="ah-{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
    f'<marker id="ahs-{c[1:]}" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M10,0 L0,5 L10,10 z" fill="{c}"/></marker>'
    for c in colors)
with open(OUT + "multi-agent-architecture.svg", "w") as f:
    f.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
            f'font-family="Helvetica, Arial, sans-serif"><defs>{defs}</defs>'
            f'<rect width="{W}" height="{H}" fill="#ffffff"/>' + "\n".join(svg) + "</svg>")
print(len(els), "elements")
