#!/usr/bin/env python3
"""Genera assets/*.svg y README.md a partir de profile.toml y data/repos.json.

Solo biblioteca estándar, salvo fontTools + brotli (subconjunto de la tipografía incrustada):
    pip install -r scripts/requirements.txt
    python3 scripts/generate.py

Es determinista: la misma entrada produce los mismos bytes (CI lo comprueba regenerando y comparando).
Todo SVG sale autocontenido (sin imágenes, scripts ni fuentes externas) porque GitHub los muestra
como <img> con una CSP que lo impide.

Tres anchos de diseño, elegidos por el README con <picture>/<source media>:
    d (840 px)  README ancho (≥ ~670 px de ancho útil, o sea escritorio)
    t (600 px)  README medio (ventanas estrechas, tabletas)
    m (360 px)  README angosto (teléfonos)
El ancho útil del README NO es el del viewport: en github.com mide viewport − 82 (< 768 px),
viewport − 370 (768–1011 px) y viewport − 434 (≥ 1012 px). Los cortes de media salen de ahí y
dejan cada variante entre 0,75× y 1,25× de su tamaño de diseño.
"""
from __future__ import annotations

import base64
import html
import io
import json
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ROOT / "scripts" / "fonts"
ICONS = ROOT / "scripts" / "icons"

WIDTH = {"d": 840, "t": 600, "m": 360}
VARIANTS = ("d", "t", "m")
# viewport → variante (ver docstring). Una lista de condiciones separada por comas es un «o».
MEDIA_M = "(max-width: 531px), (min-width: 768px) and (max-width: 819px)"
MEDIA_T = "(max-width: 767px), (min-width: 820px) and (max-width: 1099px)"

# ── paleta: azul noche con un acento por capa del pipeline ──────────────────────────────────────
BG0, BG1 = "#060b1c", "#101c40"
NODE, PIPE = "#0c1530", "#16244d"
TX, DIM = "#e8eefb", "#8ea3c8"
LINE = "#2a3d78"
ACCENTS = ["#38bdf8", "#e0893a", "#b4bfd3", "#ffc83d", "#a78bfa"]  # offers, bronze, silver, gold, observatory
GREEN = "#4ade80"

FONT_FILES = {400: "MartianMonoSemiCondensed-Regular.ttf", 700: "MartianMonoSemiCondensed-Bold.ttf"}
FALLBACK = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
# Texto pequeño (descripciones, chips, etiquetas): sans del sistema. Es más compacto que la mono y no
# cuesta bytes de fuente; su ancho varía algo según el sistema, así que se mide con margen.
SANS = "system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
SANS_ADV = 0.54
FONT_NOTE = "Martian Mono (c) The Martian Mono Project Authors, SIL Open Font License 1.1: ver docs/CREDITS.md"

_fonts: dict[int, TTFont] = {w: TTFont(FONTS / f, recalcTimestamp=False) for w, f in FONT_FILES.items()}
CMAP = _fonts[400].getBestCmap()
ADV = round(_fonts[400]["hmtx"][CMAP[ord("a")]][0] / _fonts[400]["head"].unitsPerEm, 4)
# fuente monoespaciada: todo carácter mide lo mismo (se comprueba)
assert all(
    _fonts[w]["hmtx"][CMAP[ord(c)]][0] == _fonts[w]["hmtx"][CMAP[ord("a")]][0] for w in _fonts for c in "iW0 ."
), "la fuente ya no es monoespaciada"


def tw(text: str, size: float, ls: float = 0.0) -> float:
    """Ancho exacto de una línea en la fuente mono."""
    return len(text) * (ADV * size + ls)


def tws(text: str, size: float) -> float:
    """Ancho estimado, con margen, de una línea en sans."""
    return len(text) * SANS_ADV * size


_subset_cache: dict[tuple[int, str], str] = {}


def font_b64(weight: int, chars: str) -> str:
    key = (weight, "".join(sorted(set(chars))))
    if key not in _subset_cache:
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = []
        opts.hinting = False
        opts.desubroutinize = True
        opts.name_IDs = [1, 2]
        # recalcTimestamp=False: sin esto fontTools estampa la hora actual y cada corrida da bytes distintos
        font = TTFont(FONTS / FONT_FILES[weight], recalcTimestamp=False)
        sub = subset.Subsetter(opts)
        sub.populate(text=key[1])
        sub.subset(font)
        font.flavor = "woff2"
        buf = io.BytesIO()
        font.save(buf)
        _subset_cache[key] = base64.b64encode(buf.getvalue()).decode()
    return _subset_cache[key]


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def n(x: float) -> str:
    """Número corto y estable para atributos SVG."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


class Doc:
    def __init__(self, w: int, h: int, title: str, desc: str):
        self.w, self.h, self.title, self.desc = w, h, title, desc
        self.css: list[str] = []
        self.defs: list[str] = []
        self.body: list[str] = []
        self.chars: dict[int, set[str]] = {400: set(), 700: set()}

    def t(self, x, y, text, size, weight=400, fill=TX, anchor="start", ls=0.0, cls="", extra="", sans=False) -> str:
        if not sans:
            for ch in text:
                if ord(ch) not in CMAP:
                    raise SystemExit(f"la tipografía no tiene el carácter {ch!r} (U+{ord(ch):04X}) en «{text}»")
            self.chars[weight].update(text)
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        l = f' letter-spacing="{n(ls)}"' if ls else ""
        base = "u" if sans else "t"
        c = f' class="{base} {cls}"' if cls else f' class="{base}"'
        wt = f' font-weight="{weight}"' if weight != 400 else ""
        return f'<text{c} x="{n(x)}" y="{n(y)}" font-size="{n(size)}"{wt} fill="{fill}"{a}{l}{extra}>{esc(text)}</text>'

    def add(self, *parts: str) -> None:
        self.body.extend(parts)

    def render(self) -> str:
        used = {wt: chs for wt, chs in self.chars.items() if chs}
        faces = "".join(
            f"@font-face{{font-family:'MMSC';font-weight:{wt};"
            f"src:url(data:font/woff2;base64,{font_b64(wt, ''.join(sorted(chs)))}) format('woff2')}}"
            for wt, chs in used.items()
        )
        base = f".t{{font-family:'MMSC',{FALLBACK}}}.u{{font-family:{SANS}}}"
        css = faces + base + "".join(self.css)
        note = f"<!-- {FONT_NOTE} -->" if used else ""
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}" role="img" aria-labelledby="ti de">'
            f'{note}<title id="ti">{esc(self.title)}</title><desc id="de">{esc(self.desc)}</desc>'
            f"<style>{css}</style><defs>{''.join(self.defs)}</defs>{''.join(self.body)}</svg>\n"
        )


def card_bg(d: Doc, w: int, h: int, rx: int = 22, grid: bool = True) -> None:
    """Tarjeta opaca azul noche: no depende del tema de GitHub."""
    d.defs.append(
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BG0}"/>'
        f'<stop offset="1" stop-color="{BG1}"/></linearGradient>'
    )
    d.add(f'<rect width="{w}" height="{h}" rx="{rx}" fill="url(#bg)"/>')
    if grid:
        d.defs.append(
            '<pattern id="gp" width="24" height="24" patternUnits="userSpaceOnUse">'
            '<path d="M24 0H0V24" fill="none" stroke="#7aa2ff" stroke-opacity=".07"/></pattern>'
        )
        d.add(f'<rect width="{w}" height="{h}" rx="{rx}" fill="url(#gp)"/>')


def card_border(d: Doc, w: int, h: int, rx: int = 22) -> None:
    d.add(f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="{rx}" fill="none" stroke="{LINE}" stroke-opacity=".8"/>')


def write(name: str, d: Doc) -> None:
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / name).write_text(d.render(), encoding="utf-8")


# ── íconos ───────────────────────────────────────────────────────────────────────────────────────
SAFE_TAGS = {"path", "g", "circle", "rect", "polygon", "polyline", "ellipse", "line"}
SAFE_ATTRS = {"d", "fill", "fill-rule", "clip-rule", "points", "cx", "cy", "r", "rx", "ry", "x", "y", "width",
              "height", "x1", "y1", "x2", "y2", "transform", "opacity", "fill-opacity"}


def load_icon(spec: str, color: str | None) -> tuple[str, int]:
    """Devuelve (marcado interior ya saneado, lado del viewBox) de un ícono 'si:slug' o 'devicon:slug'."""
    kind, slug = spec.split(":")
    path = ICONS / ("si" if kind == "si" else "devicon") / f"{slug}.svg"
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    vb = [float(v) for v in root.attrib["viewBox"].split()]

    def walk(el: ET.Element) -> str:
        tag = el.tag.split("}")[1]
        if tag not in SAFE_TAGS:
            raise SystemExit(f"{path}: etiqueta no permitida <{tag}>")
        attrs = []
        for k, v in el.attrib.items():
            if k not in SAFE_ATTRS:
                raise SystemExit(f"{path}: atributo no permitido {k}")
            if k == "fill" and color and kind == "si":
                continue
            attrs.append(f'{k}="{v}"')
        inner = "".join(walk(c) for c in el if not c.tag.endswith("}title"))
        return f"<{tag} {' '.join(attrs)}>{inner}</{tag}>"

    body = "".join(walk(c) for c in root if not c.tag.endswith("}title"))
    if kind == "si":
        body = f'<g fill="{color}">{body}</g>'
    return body, int(vb[2])


def icon_at(spec: str, color: str | None, cx: float, cy: float, size: float) -> str:
    body, side = load_icon(spec, color)
    return f'<g transform="translate({n(cx - size / 2)} {n(cy - size / 2)}) scale({n(size / side)})">{body}</g>'


# trazos propios (línea) para los nodos del pipeline y los logros: 28×28 centrados en (0,0)
GLYPHS = {
    "globe": '<circle r="14"/><ellipse rx="6" ry="14"/><path d="M-14 0H14"/>',
    "database": '<ellipse cy="-10" rx="13" ry="5"/><path d="M-13 -10V10C-13 14 13 14 13 10V-10M-13 0C-13 4 13 4 13 0"/>',
    "funnel": '<path d="M-14 -12H14L4 0V12L-4 8V0Z"/>',
    "gem": '<path d="M-14 -4L-8 -12H8L14 -4L0 13ZM-14 -4H14M-4 -4L0 13L4 -4"/>',
    "eye": '<path d="M-16 0C-9 -11 9 -11 16 0C9 11 -9 11 -16 0Z"/><circle r="5"/>',
    "trophy": '<path d="M-8 -12H8V0C8 6 4 9 0 9C-4 9 -8 6 -8 0ZM-8 -8H-14C-14 -2 -11 1 -8 1M8 -8H14C14 -2 11 1 8 1M0 9V14M-6 14H6"/>',
    "flag": '<path d="M-10 -14V14M-10 -12H10L5 -6L10 0H-10"/>',
    "bolt": '<path d="M3 -14L-9 2H-1L-3 14L9 -2H1Z"/>',
    "mail": '<rect x="-14" y="-10" width="28" height="20" rx="4"/><path d="M-13 -8L0 2L13 -8"/>',
    "arrow": '<path d="M-6 6L6 -6M-2 -6H6V2"/>',
}


def glyph(name: str, cx: float, cy: float, color: str, sw: float = 2.6, scale: float = 1.0) -> str:
    return (
        f'<g transform="translate({n(cx)} {n(cy)}) scale({n(scale)})" fill="none" stroke="{color}" '
        f'stroke-width="{n(sw / scale)}" stroke-linecap="round" stroke-linejoin="round">{GLYPHS[name]}</g>'
    )


def wrap(text: str, size: float, max_w: float) -> list[str]:
    """Reparte texto sans en líneas que caben en max_w (estimación con margen)."""
    per = int(max_w // (SANS_ADV * size))
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if len(trial) <= per:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# ── piezas ───────────────────────────────────────────────────────────────────────────────────────
SECTION = {
    "d": dict(h=46, size=15, ls=3.0, pad=24, gap=14),
    "t": dict(h=44, size=14, ls=2.6, pad=22, gap=12),
    "m": dict(h=42, size=13, ls=2.2, pad=20, gap=10),
}


def section(label: str, idx: int, v: str) -> Doc:
    s = SECTION[v]
    w, h, size, ls = WIDTH[v], s["h"], s["size"], s["ls"]
    d = Doc(w, h, label, f"Section heading: {label}")
    card_bg(d, w, h, rx=12, grid=False)
    acc = ACCENTS[(idx - 1) % 5]
    d.add(f'<rect x="0" y="0" width="4" height="{h}" fill="{acc}"/>')
    num = f"{idx:02d}"
    y = h / 2 + size * 0.35
    d.add(d.t(s["pad"] + 4, y, num, size, 700, acc, ls=ls))
    tx = s["pad"] + 4 + tw(num, size, ls) + s["gap"]
    title = label.upper()
    d.add(d.t(tx, y, title, size, 700, TX, ls=ls))
    lx = tx + tw(title, size, ls) + 14
    d.defs.append(
        f'<linearGradient id="ln" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="{LINE}"/>'
        f'<stop offset="1" stop-color="{LINE}" stop-opacity="0"/></linearGradient>'
    )
    if lx < w - 24:
        d.add(f'<rect x="{n(lx)}" y="{n(h / 2 - 0.5)}" width="{n(w - 12 - lx)}" height="1" fill="url(#ln)"/>')
    card_border(d, w, h, 12)
    return d


def wave_path(h: int, amp: float, period: float, y: float, total: float) -> str:
    half = period / 2
    cnt = int(total / half) + 2
    p = f"M0,{n(y)} Q{n(half / 2)},{n(y - 2 * amp)} {n(half)},{n(y)}"
    p += "".join(f" T{n((i + 1) * half)},{n(y)}" for i in range(1, cnt))
    return p + f" V{h} H0 Z"


HERO = {
    "d": dict(h=262, pad=48, nm=60, ph=26, nm_y=130, ph_y=192, tag="affiliation", tag_size=12, tag_ls=2.2, tag_y=62, ribbon=140, wy=(36, 62)),
    "t": dict(h=250, pad=40, nm=50, ph=24, nm_y=122, ph_y=182, tag="tag_short", tag_size=11, tag_ls=2.0, tag_y=58, ribbon=110, wy=(36, 62)),
    "m": dict(h=262, pad=24, nm=34, ph=17, nm_y=118, ph_y=176, tag="tag_short", tag_size=10.5, tag_ls=1.4, tag_y=52, ribbon=0, wy=(30, 52)),
}


def hero(P: dict, v: str) -> Doc:
    per = P["person"]
    c_ = HERO[v]
    w, h, pad = WIDTH[v], c_["h"], c_["pad"]
    nm_size, ph_size = c_["nm"], c_["ph"]
    d = Doc(w, h, f"{per['name']} — " + ", ".join(per["phrases"][:3]), "Animated banner: name, moving waves and a line that types and rotates specialties.")
    tag = per[c_["tag"]].upper()
    assert pad + tw(tag, c_["tag_size"], c_["tag_ls"]) < w - pad - c_["ribbon"] - 8, "la etiqueta de hero pisa la cinta de capas"
    assert tw(per["name"], nm_size) < w - 2 * pad, "nombre demasiado ancho"
    phrases = per["phrases"]
    assert max(len(p) for p in phrases) * ADV * ph_size < w - 2 * pad - 2 * ADV * ph_size - 10, "frase demasiado larga"

    TYPE, HOLD, DEL, GAP = 0.075, 1.8, 0.035, 0.35
    slots, t0 = [], 0.0
    for p in phrases:
        L = len(p)
        a = t0
        b = a + L * TYPE
        c = b + HOLD
        e = c + L * DEL
        slots.append((p, L, a, b, c, e))
        t0 = e + GAP
    T = round(t0, 2)
    pc = lambda x: round(100 * x / T, 3)
    cw = ADV * ph_size
    p1, p2 = w // 2, w * 3 // 4  # el desplazamiento de cada ola es exactamente su periodo: el bucle no da saltos

    css = [
        "@keyframes bg{to{transform:translateX(-%dpx)}}" % w,
        "@keyframes w1{to{transform:translateX(-%dpx)}}" % p1,
        "@keyframes w2{to{transform:translateX(-%dpx)}}" % p2,
        "@keyframes breathe{0%,100%{opacity:.35}50%{opacity:.7}}",
        "@keyframes rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}",
        "@keyframes blink{50%{opacity:0}}",
        "@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}",
        "#bgr{animation:bg 18s linear infinite}",
        "#w1{animation:w1 16s linear infinite}",
        "#w2{animation:w2 24s linear infinite}",
        "#glow{animation:breathe 6s ease-in-out infinite}",
        ".rise{animation:rise .9s cubic-bezier(.2,.7,.2,1) both}.rise2{animation-delay:.2s}.rise3{animation-delay:.4s}",
        ".led{animation:pulse 1.6s ease-in-out infinite}",
        ".blink{animation:blink 1s steps(1) infinite}",
        # sin animación (lector estático, preferencia del usuario) queda la primera frase completa y sin cursor
        ".ph{opacity:0}.ph0{opacity:1}.cur{opacity:0}",
    ]
    for i, (p, L, a, b, c, e) in enumerate(slots):
        css.append(
            f"@keyframes k{i}{{0%,{pc(a)}%{{opacity:1;clip-path:inset(0 100% 0 0);animation-timing-function:steps({L},end)}}"
            f"{pc(b)}%,{pc(c)}%{{opacity:1;clip-path:inset(0 0 0 0);animation-timing-function:steps({L},end)}}"
            f"{pc(e)}%{{opacity:1;clip-path:inset(0 100% 0 0)}}"
            f"{min(pc(e) + 0.001, 100)}%,100%{{opacity:0;clip-path:inset(0 100% 0 0)}}}}"
        )
        pre = "" if a == 0 else f"0%,{pc(a) - 0.001}%{{opacity:0;transform:translateX(0)}}"
        css.append(
            f"@keyframes c{i}{{{pre}{pc(a)}%{{opacity:1;transform:translateX(0);animation-timing-function:steps({L},end)}}"
            f"{pc(b)}%,{pc(c)}%{{opacity:1;transform:translateX({n(L * cw)}px);animation-timing-function:steps({L},end)}}"
            f"{pc(e)}%{{opacity:1;transform:translateX(0)}}"
            f"{min(pc(e) + 0.001, 100)}%,100%{{opacity:0;transform:translateX(0)}}}}"
        )
        css.append(f".ph{i}{{animation:k{i} {T}s linear infinite}}.cu{i}{{animation:c{i} {T}s linear infinite}}")
    css.append("@media (prefers-reduced-motion:reduce){*{animation:none!important}.ph0{clip-path:none!important}.cur{display:none}}")
    d.css.extend(css)

    d.defs.append(
        f'<linearGradient id="bgg" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{w}" y2="0" spreadMethod="repeat">'
        f'<stop offset="0" stop-color="{BG0}"/><stop offset=".5" stop-color="#0d2b66"/><stop offset="1" stop-color="{BG0}"/></linearGradient>'
        f'<linearGradient id="vf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{BG0}" stop-opacity="0"/>'
        f'<stop offset="1" stop-color="{BG0}" stop-opacity=".85"/></linearGradient>'
        '<radialGradient id="gl"><stop offset="0" stop-color="#38bdf8" stop-opacity=".55"/>'
        '<stop offset="1" stop-color="#38bdf8" stop-opacity="0"/></radialGradient>'
        f'<clipPath id="frame"><rect width="{w}" height="{h}" rx="22"/></clipPath>'
    )
    wy1, wy2 = h - c_["wy"][0], h - c_["wy"][1]
    d.add(
        '<g clip-path="url(#frame)">',
        f'<rect width="{w}" height="{h}" fill="{BG0}"/>',
        f'<rect id="bgr" x="0" y="0" width="{w * 3}" height="{h}" fill="url(#bgg)"/>',
        f'<circle id="glow" cx="{n(w * 0.2)}" cy="{n(h * 0.42)}" r="{n(h * 0.8)}" fill="url(#gl)"/>',
        f'<path id="w2" d="{wave_path(h, 14, p2, wy2, w * 4)}" fill="#1d6fd8" fill-opacity=".22"/>',
        f'<path id="w1" d="{wave_path(h, 11, p1, wy1, w * 3)}" fill="#38bdf8" fill-opacity=".16"/>',
        f'<rect width="{w}" height="{h}" fill="url(#vf)"/>',
        f'<g class="rise">{d.t(pad, c_["tag_y"], tag, c_["tag_size"], 400, "#a9bbdb", ls=c_["tag_ls"])}</g>',
        f'<g class="rise rise2">{d.t(pad, c_["nm_y"], per["name"], nm_size, 700, "#ffffff", ls=-1)}</g>',
    )
    ph_y = c_["ph_y"]
    px = pad + (14 if v == "m" else 20)
    d.add(
        f'<g class="rise rise3"><circle class="led" cx="{pad + 4}" cy="{n(ph_y - ph_size * 0.35)}" r="4" fill="{GREEN}"/>'
        f'{d.t(px + 2, ph_y, ">", ph_size, 700, ACCENTS[0])}</g>'
    )
    tx = px + 2 + ADV * ph_size * 2
    for i, (p, L, *_rest) in enumerate(slots):
        d.add(d.t(tx, ph_y, p, ph_size, 400, TX, cls=f"ph ph{i}", extra=f' textLength="{n(L * cw)}" lengthAdjust="spacing"'))
    for i in range(len(slots)):
        d.add(
            f'<g class="cur cu{i}"><rect class="blink" x="{n(tx + 2)}" y="{n(ph_y - ph_size + 3)}" width="3" '
            f'height="{n(ph_size + 2)}" rx="1" fill="{ACCENTS[0]}"/></g>'
        )
    if c_["ribbon"]:  # cinta de capas: eco del pipeline
        span = c_["ribbon"]
        rx0, ry = w - pad - span - 10, c_["tag_y"] - 4
        d.add(f'<rect x="{rx0}" y="{ry - 0.5}" width="{span}" height="1" fill="{LINE}"/>')
        for i, col in enumerate(ACCENTS):
            d.add(f'<circle cx="{n(rx0 + span * i / 4)}" cy="{ry}" r="4.5" fill="{col}"/>')
    d.add("</g>")
    card_border(d, w, h)
    return d


PIPE_CFG = {
    "d": dict(h=330, x0=100, y0=156, step=160, tile=76, rx=18, name=22, sub=15, hdr=14, hdr_y=44, pad=28, foot=12, fls=2.0, foot_y=28, gl=1.0, ngap=34, sgap=58),
    "t": dict(h=296, x0=76, y0=138, step=112, tile=64, rx=16, name=18, sub=14, hdr=13, hdr_y=40, pad=24, foot=11, fls=1.8, foot_y=26, gl=0.9, ngap=30, sgap=50),
    "m": dict(h=680, x0=72, y0=128, step=108, tile=64, rx=16, name=22, sub=15, hdr=12, hdr_y=40, pad=20, foot=11, fls=1.6, foot_y=0, gl=0.9, ngap=0, sgap=0),
}


def pipeline(P: dict, v: str) -> Doc:
    pl = P["pipeline"]
    nodes = pl["nodes"]
    N = len(nodes)
    c_ = PIPE_CFG[v]
    vertical = v == "m"
    w, h = WIDTH[v], c_["h"]
    d = Doc(
        w,
        h,
        "Data pipeline: " + ", ".join(x["name"] for x in nodes),
        "Animated data pipeline: particles flow from the scraped job offers through bronze, silver and gold to the observatory.",
    )
    card_bg(d, w, h)
    d.css.extend(
        [
            "@keyframes flow{to{stroke-dashoffset:-16}}",
            "@keyframes pulse{0%,100%{opacity:.25}25%{opacity:1}}",
            ".fl{stroke-width:3.5;stroke-linecap:round;stroke-dasharray:1 15;fill:none;animation:flow .9s linear infinite}",
            ".ha{opacity:.25;animation:pulse 1.5s ease-out infinite}",
            ".pp{stroke:%s;stroke-width:10;stroke-linecap:round;fill:none}" % PIPE,
            ".s{display:none}",
            # SMIL no obedece a la regla CSS: las partículas viven en capas .m (se ocultan) y hay capas .s quietas
            "@media (prefers-reduced-motion:reduce){*{animation:none!important}.m{display:none}.s{display:inline}}",
        ]
    )
    pad = c_["pad"]
    d.add(d.t(pad, c_["hdr_y"], "DATA PIPELINE", c_["hdr"], 700, DIM, ls=3))
    d.add(d.t(w - pad, c_["hdr_y"], pl["code"], c_["hdr"], 700, TX, anchor="end", ls=2))

    step, tile = c_["step"], c_["tile"]
    pos = [(c_["x0"], c_["y0"] + step * i) if vertical else (c_["x0"] + step * i, c_["y0"]) for i in range(N)]
    half, gap = tile / 2, 8
    main = f"M{pos[0][0]} {pos[0][1]}" + (f"V{pos[-1][1]}" if vertical else f"H{pos[-1][0]}")
    d.defs.append(f'<path id="main" d="{main}"/>')
    for i in range(N - 1):
        (xa, ya), (xb, yb) = pos[i], pos[i + 1]
        if vertical:
            seg = f"M{xa} {n(ya + half + gap)}V{n(yb - half - gap)}"
            gx = f'x1="0" y1="{n(ya + half)}" x2="0" y2="{n(yb - half)}"'
        else:
            seg = f"M{n(xa + half + gap)} {ya}H{n(xb - half - gap)}"
            gx = f'x1="{n(xa + half)}" y1="0" x2="{n(xb - half)}" y2="0"'
        d.defs.append(
            f'<linearGradient id="e{i}" gradientUnits="userSpaceOnUse" {gx}>'
            f'<stop offset="0" stop-color="{nodes[i]["color"]}"/><stop offset="1" stop-color="{nodes[i + 1]["color"]}"/></linearGradient>'
        )
        d.add(f'<path d="{seg}" class="pp"/><path d="{seg}" class="fl" stroke="url(#e{i})"/>')
    for i, (x, y) in enumerate(pos):
        col = nodes[i]["color"]
        d.defs.append(
            f'<radialGradient id="h{i}"><stop offset="0" stop-color="{col}" stop-opacity=".55"/>'
            f'<stop offset="1" stop-color="{col}" stop-opacity="0"/></radialGradient>'
        )
        delay = n(-0.375 + 0.375 * i if i < N - 1 else -0.375)
        d.add(f'<circle cx="{x}" cy="{y}" r="{n(half * 0.82)}" fill="url(#h{i})" class="ha" style="animation-delay:{delay}s"/>')
    dur, count = 7.5, 5
    colors = ";".join(nodes[i]["color"] for i in range(N - 1))
    kt = ";".join(n(i / (N - 1)) for i in range(N - 1))
    for k in range(count):
        begin = -k * dur / count
        d.add(
            f'<g class="m" style="color:{nodes[0]["color"]}"><circle r="11" fill="currentColor" fill-opacity=".22"/>'
            f'<circle r="5" fill="currentColor"/><animateMotion dur="{dur}s" begin="{n(begin)}s" repeatCount="indefinite">'
            f'<mpath xlink:href="#main"/></animateMotion><animate attributeName="color" calcMode="discrete" '
            f'values="{colors}" keyTimes="{kt}" dur="{dur}s" begin="{n(begin)}s" repeatCount="indefinite"/></g>'
        )
    for i in range(N - 1):
        (xa, ya), (xb, yb) = pos[i], pos[i + 1]
        mx, my = n((xa + xb) / 2), n((ya + yb) / 2)
        d.add(
            f'<g class="s" style="color:{nodes[i]["color"]}"><circle cx="{mx}" cy="{my}" r="9" fill="currentColor" fill-opacity=".2"/>'
            f'<circle cx="{mx}" cy="{my}" r="4" fill="currentColor"/></g>'
        )
    for i, (x, y) in enumerate(pos):
        col = nodes[i]["color"]
        d.add(
            f'<rect x="{n(x - half)}" y="{n(y - half)}" width="{tile}" height="{tile}" rx="{c_["rx"]}" fill="{NODE}" stroke="{col}" stroke-width="2"/>',
            glyph(nodes[i]["icon"], x, y, col, 3, c_["gl"]),
        )
        if vertical:
            d.add(d.t(x + half + 20, y - 2, nodes[i]["name"], c_["name"], 700, TX), d.t(x + half + 20, y + 22, nodes[i]["sub"], c_["sub"], 400, DIM, sans=True))
        else:
            d.add(
                d.t(x, y + half + c_["ngap"], nodes[i]["name"], c_["name"], 700, TX, anchor="middle"),
                d.t(x, y + half + c_["sgap"], nodes[i]["sub"], c_["sub"], 400, DIM, anchor="middle", sans=True),
            )
    fl, fr = pl["footer_left"].upper(), pl["footer_right"].upper()
    if vertical:
        d.add(d.t(pad, h - 44, fl, c_["foot"], 400, DIM, ls=c_["fls"]), d.t(pad, h - 24, fr, c_["foot"], 400, DIM, ls=c_["fls"]))
    else:
        d.add(d.t(pad, h - c_["foot_y"], fl, c_["foot"], 400, DIM, ls=c_["fls"]), d.t(w - pad, h - c_["foot_y"], fr, c_["foot"], 400, DIM, anchor="end", ls=c_["fls"]))
        assert tw(fl, c_["foot"], c_["fls"]) + tw(fr, c_["foot"], c_["fls"]) < w - 2 * pad - 20, "el pie del pipeline no cabe"
    card_border(d, w, h)
    return d


def achievements(P: dict, v: str) -> Doc:
    items = P["achievements"]["items"]
    w = WIDTH[v]
    gap = 24 if v == "d" else 12
    stacked = v != "d"
    ch = 104 if stacked else 148
    cw_ = w if stacked else (w - gap * (len(items) - 1)) // len(items)
    h = len(items) * ch + (len(items) - 1) * gap if stacked else ch
    d = Doc(w, h, "Highlights", "Highlights: " + "; ".join(f"{i['big']} {i['label']} ({i['detail']})" for i in items))
    for k, it in enumerate(items):
        x, y = (0, k * (ch + gap)) if stacked else (k * (cw_ + gap), 0)
        c = it["accent"]
        d.defs.append(
            f'<linearGradient id="g{k}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BG0}"/>'
            f'<stop offset="1" stop-color="{BG1}"/></linearGradient>'
            f'<radialGradient id="r{k}" cx="1" cy="0" r="1"><stop offset="0" stop-color="{c}" stop-opacity=".22"/>'
            f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>'
            f'<clipPath id="c{k}"><rect x="{x}" y="{y}" width="{cw_}" height="{ch}" rx="18"/></clipPath>'
        )
        d.add(
            f'<g clip-path="url(#c{k})"><rect x="{x}" y="{y}" width="{cw_}" height="{ch}" fill="url(#g{k})"/>'
            f'<rect x="{x}" y="{y}" width="{cw_}" height="{ch}" fill="url(#r{k})"/>'
            f'<rect x="{x}" y="{y}" width="5" height="{ch}" fill="{c}"/></g>'
            f'<rect x="{x + .5}" y="{y + .5}" width="{cw_ - 1}" height="{ch - 1}" rx="18" fill="none" stroke="{LINE}" stroke-opacity=".8"/>'
        )
        big = it["big"]
        if stacked:
            d.add(
                glyph(it["icon"], x + 34, y + 31, c, 2.2, 0.7),
                d.t(x + 54, y + 36, it["label"], 14, 700, TX),
                d.t(x + cw_ - 22, y + 70, big, 40, 700, c, anchor="end"),
            )
            lines = wrap(it["detail"], 13, cw_ - 24 - tw(big, 40) - 40)
            assert tw(it["label"], 14) + 54 < cw_ - 20, it
            ty = y + 64
        else:
            d.add(
                glyph(it["icon"], x + 36, y + 32, c, 2.2, 0.75),
                d.t(x + 58, y + 37, it["label"], 14, 700, TX),
                d.t(x + 26, y + 94, big, 48, 700, c),
            )
            lines = wrap(it["detail"], 13, cw_ - 52)
            assert tw(it["label"], 14) + 58 + 20 < cw_, it
            ty = y + 118
        assert len(lines) <= 2, f"el detalle de «{it['label']}» ocupa {len(lines)} líneas"
        for j, ln in enumerate(lines):
            d.add(d.t(x + 26 if not stacked else x + 24, ty + 18 * j, ln, 13, 400, DIM, sans=True))
    return d


def project_card(p: dict) -> Doc:
    w, h = 410, 170
    d = Doc(w, h, p["title"], f"{p['title']}: {p['desc']} Tech: {', '.join(p['chips'])}.")
    card_bg(d, w, h, rx=18, grid=False)
    d.defs.append(f'<clipPath id="cp"><rect width="{w}" height="{h}" rx="18"/></clipPath>')
    if p["accent"] == "multi":
        stops = "".join(f'<stop offset="{n(i / 4)}" stop-color="{c}"/>' for i, c in enumerate(ACCENTS))
        d.defs.append(f'<linearGradient id="ac" x1="0" y1="0" x2="0" y2="1">{stops}</linearGradient>')
        acc_fill, acc = "url(#ac)", ACCENTS[0]
    else:
        acc_fill = acc = p["accent"]
    d.defs.append(
        f'<radialGradient id="rg" cx="1" cy="0" r="1"><stop offset="0" stop-color="{acc}" stop-opacity=".16"/>'
        f'<stop offset="1" stop-color="{acc}" stop-opacity="0"/></radialGradient>'
    )
    d.add(f'<g clip-path="url(#cp)"><rect width="{w}" height="{h}" fill="url(#rg)"/><rect width="5" height="{h}" fill="{acc_fill}"/></g>')
    pad = 26
    d.add(d.t(pad, 34, p["tag"], 11, 400, "#a9bbdb", ls=1.4))
    assert tw(p["tag"], 11, 1.4) < w - 2 * pad, p["tag"]
    d.add(d.t(pad, 64, p["title"], 20, 700, TX))
    assert tw(p["title"], 20) < w - 2 * pad, p["title"]
    lines = wrap(p["desc"], 14, w - 2 * pad)
    assert len(lines) <= 2, f"descripción de «{p['title']}» ocupa {len(lines)} líneas"
    for i, ln in enumerate(lines):
        d.add(d.t(pad, 91 + 20 * i, ln, 14, 400, "#a9bbdb", sans=True))
    x, cy = pad, 132
    for chip in p["chips"]:
        cwid = tws(chip, 12) + 20
        d.add(
            f'<rect x="{n(x)}" y="{cy}" width="{n(cwid)}" height="24" rx="12" fill="#ffffff" fill-opacity=".06" stroke="#7aa2ff" stroke-opacity=".28"/>',
            d.t(x + cwid / 2, cy + 16.5, chip, 12, 400, TX, anchor="middle", sans=True),
        )
        x += cwid + 8
    link = p["link"]
    lw = tws(link, 12.5) + 18
    assert x - 8 + 14 + lw < w - pad + 4, f"chips y enlace de «{p['title']}» no caben: {x - 8 + 14 + lw} vs {w - pad}"
    d.add(d.t(w - pad - 16, cy + 16.5, link, 12.5, 700, acc, anchor="end", sans=True), glyph("arrow", w - pad - 7, cy + 12, acc, 2.2, 0.55))
    card_border(d, w, h, 18)
    return d


SKILLS = {
    "d": dict(pitch=78, tile=60, per_row=7, stack=False, lab=12.5),
    "t": dict(pitch=76, tile=54, per_row=7, stack=True, lab=12),
    "m": dict(pitch=76, tile=54, per_row=4, stack=True, lab=12),
}


def skills(P: dict, v: str) -> Doc:
    groups = P["skills"]
    c_ = SKILLS[v]
    w, pitch, tile, per_row, stack = WIDTH[v], c_["pitch"], c_["tile"], c_["per_row"], c_["stack"]
    x0 = (w - ((per_row - 1) * pitch + tile)) / 2 if stack else 232
    y = 18
    layout = []
    for g in groups:
        rows = [g["items"][i : i + per_row] for i in range(0, len(g["items"]), per_row)]
        layout.append((g, y, rows))
        y += (30 + len(rows) * 84 + 4) if stack else max(len(rows) * 88, 88)
    h = int(y + 10)
    d = Doc(w, h, "Toolbox", "Technologies grouped by area: " + "; ".join(f"{g['group']}: {', '.join(i['label'] for i in g['items'])}" for g in groups))
    card_bg(d, w, h)
    for g, gy, rows in layout:
        acc = g["accent"]
        if stack:
            d.add(f'<rect x="{n(x0)}" y="{gy + 6}" width="3" height="12" rx="1.5" fill="{acc}"/>', d.t(x0 + 10, gy + 17, g["group"].upper(), 11.5, 700, acc, ls=2.2))
        else:
            d.add(f'<rect x="40" y="{gy + 14}" width="3" height="16" rx="1.5" fill="{acc}"/>', d.t(52, gy + 27, g["group"].upper(), 12, 700, acc, ls=2))
            assert tw(g["group"].upper(), 12, 2) < x0 - 52 - 8, g["group"]
        for r, row in enumerate(rows):
            for c, it in enumerate(row):
                tx_ = x0 + c * pitch
                ty_ = gy + 30 + r * 84 if stack else gy + r * 88
                cx, cy = tx_ + tile / 2, ty_ + tile / 2
                dev = it["icon"].startswith("devicon")
                isz = (34 if dev else 30) if not stack else (30 if dev else 26)
                d.add(
                    f'<rect x="{n(tx_)}" y="{n(ty_)}" width="{tile}" height="{tile}" rx="{14 if not stack else 13}" fill="{NODE}" stroke="{LINE}"/>',
                    icon_at(it["icon"], it.get("color"), cx, cy, isz),
                )
                lab = it["label"]
                size = min(c_["lab"], (pitch - 6) / (SANS_ADV * len(lab)))
                assert size >= 10, f"la etiqueta «{lab}» quedaría a {size:.1f}px"
                d.add(d.t(cx, ty_ + tile + 17, lab, size, 400, "#a9bbdb", anchor="middle", sans=True))
    card_border(d, w, h)
    return d


LANG_COLORS = {
    "Jupyter Notebook": "#da5b0b", "Python": "#3572a5", "JavaScript": "#f1e05a", "CSS": "#8a5fd6", "Kotlin": "#a97bff",
    "C": "#9aa4b2", "C++": "#f34b7d", "TypeScript": "#3178c6", "HTML": "#e34c26", "Shell": "#89e051",
}


def top_languages(R: dict) -> tuple[list[tuple[str, int]], int, int]:
    repos = [r for r in R["repos"] if not r["fork"] and not r.get("archived")]
    langs: dict[str, int] = {}
    last: dict[str, str] = {}
    for r in repos:
        if r.get("language"):
            langs[r["language"]] = langs.get(r["language"], 0) + 1
            last[r["language"]] = max(last.get(r["language"], ""), r.get("created_at", ""))
    # empates: gana el lenguaje del repo más nuevo (created_at no cambia con cada push: datos estables, sin commits vacíos)
    by_recent = sorted(langs.items(), key=lambda kv: last[kv[0]], reverse=True)
    top = sorted(by_recent, key=lambda kv: -kv[1])[:5]
    return top, len(repos), len(langs)


def stats(P: dict, R: dict, v: str) -> Doc:
    top, n_repos, n_langs = top_languages(R)
    kpis = [(str(n_repos), "original repos"), (str(n_langs), "languages"), (str(P["stats"]["since"]), "member since")]
    stack = v != "d"
    w = WIDTH[v]
    h = (108 + 28 * len(top) + 40) if stack else 218
    d = Doc(w, h, "Public repositories by language", "Public repositories by language: " + ", ".join(f"{k} {c}" for k, c in top) + ".")
    card_bg(d, w, h)
    mx = top[0][1] if top else 1
    if stack:
        colw = (w - 48) / 3
        for i, (val, lab) in enumerate(kpis):
            x = 24 + i * colw
            d.add(d.t(x, 56, val, 34, 700, TX), d.t(x, 77, lab, 12, 400, DIM, sans=True))
            assert tw(val, 34) < colw - 8 and tws(lab, 12) < colw - 8, (val, lab)
        bar_x, bar_w = 150, w - 150 - 54
        for i, (lg, cnt) in enumerate(top):
            y = 108 + i * 28
            col = LANG_COLORS.get(lg, "#5b7bd5")
            d.add(
                d.t(24, y + 11, lg, 12.5, 400, TX, sans=True),
                f'<rect x="{bar_x}" y="{y + 2}" width="{bar_w}" height="10" rx="5" fill="{PIPE}"/>',
                f'<rect x="{bar_x}" y="{y + 2}" width="{n(bar_w * cnt / mx)}" height="10" rx="5" fill="{col}"/>',
                d.t(w - 24, y + 11, str(cnt), 12, 700, DIM, anchor="end", sans=True),
            )
    else:
        for i, (val, lab) in enumerate(kpis):
            y = 56 + i * 52
            d.add(d.t(40, y, val, 38, 700, TX), d.t(40 + tw("2023", 38) + 14, y - 3, lab, 13.5, 400, DIM, sans=True))
        bar_x, bar_w = 440, 300
        d.add(d.t(bar_x - 150, 40, "PUBLIC REPOS BY LANGUAGE", 11, 700, DIM, ls=2))
        for i, (lg, cnt) in enumerate(top):
            y = 62 + i * 25
            col = LANG_COLORS.get(lg, "#5b7bd5")
            d.add(
                d.t(bar_x - 150, y + 11, lg, 13, 400, TX, sans=True),
                f'<rect x="{bar_x}" y="{y + 1}" width="{bar_w}" height="12" rx="6" fill="{PIPE}"/>',
                f'<rect x="{bar_x}" y="{y + 1}" width="{n(bar_w * cnt / mx)}" height="12" rx="6" fill="{col}"/>',
                d.t(bar_x + bar_w + 18, y + 12, str(cnt), 13, 700, DIM, sans=True),
            )
    foot = f"includes coursework · as of {R['generated']}"
    d.add(d.t(24 if stack else 40, h - 16, foot, 11, 400, DIM, sans=True))
    assert tws(foot, 11) < w - 48, "el pie de la tarjeta de stats no cabe"
    card_border(d, w, h)
    return d


def contact_pill(kind: str, label: str, color: str) -> Doc:
    w, h = 188, 46
    d = Doc(w, h, label, f"Contact: {label}")
    card_bg(d, w, h, rx=23, grid=False)
    d.add(f'<rect x=".75" y=".75" width="{w - 1.5}" height="{h - 1.5}" rx="22.25" fill="none" stroke="{color}" stroke-opacity=".7" stroke-width="1.5"/>')
    if kind == "linkedin":
        d.add(f'<rect x="20" y="13" width="20" height="20" rx="4" fill="{color}"/>', d.t(30, 28.5, "in", 13, 700, "#06101f", anchor="middle"))
    elif kind == "email":
        d.add(glyph("mail", 30, 23, color, 2.2, 0.75))
    else:
        d.add(glyph("globe", 30, 23, color, 2.2, 0.7))
    d.add(d.t(52, 28.5, label, 15, 700, TX))
    return d


# ── README ───────────────────────────────────────────────────────────────────────────────────────
def pic(name: str, alt: str, link: str | None = None) -> str:
    """Una pieza con sus tres variantes. Todo en una línea: así el saneado de GitHub no parte el <picture>."""
    img = (
        f'<picture><source media="{MEDIA_M}" srcset="assets/{name}-m.svg">'
        f'<source media="{MEDIA_T}" srcset="assets/{name}-t.svg">'
        f'<img src="assets/{name}-d.svg" alt="{esc(alt)}" width="840"></picture>'
    )
    return f'<a href="{link}">{img}</a>' if link else img


def sec(i: int, label: str) -> str:
    """Franja de sección dentro de un <h3>: hay encabezados reales (navegación por teclado y lectores de pantalla)."""
    return f'<h3 align="center">{pic(f"sec-{i}", label)}</h3>'


def readme(P: dict, R: dict) -> str:
    per, c, pl, ach = P["person"], P["contact"], P["pipeline"], P["achievements"]
    top, n_repos, _ = top_languages(R)
    out: list[str] = []
    a = out.append
    a("<!-- Generado por scripts/generate.py desde profile.toml: no editar a mano. -->")
    a('<div align="center">\n')
    a(pic("hero", f"{per['name']}: " + ", ".join(per["phrases"][:3])))
    a("")
    a(f"**{per['tagline_en']}**  ")
    a(f"<sub>{per['tagline_es']}</sub>\n")
    a(sec(1, "Featured project"))
    a("")
    a(pic("pipeline", "Animated data pipeline: Offers, Bronze, Silver, Gold, Observatory", link=pl["page"]))
    a("")
    a(f"<sub>{pl['caption_en']} <a href=\"{pl['page']}\">Project page</a></sub>  ")
    a(f"<sub><i>{pl['caption_es']}</i></sub>\n")
    a(sec(2, "Highlights"))
    a("")
    a(pic("achievements", "Highlights: " + "; ".join(f"{i['big']} {i['label']}, {i['detail']}" for i in ach["items"])))
    a("")
    a(f"<sub>{ach['certs_en']}</sub>  ")
    a(f"<sub><i>{ach['certs_es']}</i></sub>\n")
    a(sec(3, "Selected work"))
    a("")
    a(
        " ".join(
            f'<a href="{p["url"]}"><img src="assets/project-{i + 1}.svg" alt="{esc(p["title"])}: {esc(p["desc"])}" width="410"></a>'
            for i, p in enumerate(P["projects"])
        )
        + "\n"
    )
    a(sec(4, "Toolbox"))
    a("")
    a(pic("skills", "Toolbox: " + "; ".join(f"{g['group']}: {', '.join(i['label'] for i in g['items'])}" for g in P["skills"])))
    a("")
    a(sec(5, "Public repositories"))
    a("")
    a(pic("stats", f"{n_repos} original public repositories, by language: " + ", ".join(f"{k} {v}" for k, v in top)))
    a("")
    a(sec(6, "Contact"))
    a("")
    a(
        " ".join(
            [
                f'<a href="{c["linkedin"]}"><img src="assets/contact-linkedin.svg" alt="LinkedIn" width="188"></a>',
                f'<a href="mailto:{c["email"]}"><img src="assets/contact-email.svg" alt="Email" width="188"></a>',
                f'<a href="{c["website"]}"><img src="assets/contact-website.svg" alt="Website" width="188"></a>',
            ]
        )
        + "\n"
    )
    a(f"<sub>{per['open_en']} · <i>{per['open_es']}</i> — {per['location']}</sub>\n")
    a("</div>")
    return "\n".join(out) + "\n"


def main() -> None:
    P = tomllib.loads((ROOT / "profile.toml").read_text(encoding="utf-8"))
    R = json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))
    ASSETS.mkdir(exist_ok=True)
    for old in ASSETS.glob("*.svg"):
        old.unlink()
    labels = ["Featured project", "Highlights", "Selected work", "Toolbox", "Public repositories", "Contact"]
    for v in VARIANTS:
        write(f"hero-{v}.svg", hero(P, v))
        write(f"pipeline-{v}.svg", pipeline(P, v))
        write(f"achievements-{v}.svg", achievements(P, v))
        write(f"skills-{v}.svg", skills(P, v))
        write(f"stats-{v}.svg", stats(P, R, v))
        for i, label in enumerate(labels, 1):
            write(f"sec-{i}-{v}.svg", section(label, i, v))
    for i, p in enumerate(P["projects"]):
        write(f"project-{i + 1}.svg", project_card(p))
    write("contact-linkedin.svg", contact_pill("linkedin", "LinkedIn", ACCENTS[0]))
    write("contact-email.svg", contact_pill("email", "Email", ACCENTS[3]))
    write("contact-website.svg", contact_pill("website", "Website", ACCENTS[4]))
    (ROOT / "README.md").write_text(readme(P, R), encoding="utf-8")
    total = sum(f.stat().st_size for f in ASSETS.glob("*.svg"))
    print(f"{len(list(ASSETS.glob('*.svg')))} SVG, {total / 1024:.1f} KB en total; ADV={ADV}")


if __name__ == "__main__":
    sys.exit(main())
