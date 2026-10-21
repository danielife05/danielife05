#!/usr/bin/env python3
"""Puerta de calidad del perfil: falla (código 1) si algo del README o de assets/ rompería en GitHub.

Solo biblioteca estándar. Se ejecuta en CI y a mano:
    python3 scripts/check.py            # estructura (rápido, sin red)
    python3 scripts/check.py --links    # además comprueba que cada enlace https responda

Por qué cada regla existe (cada una es una restricción medida de GitHub o un fallo que ya ocurrió):
  - GitHub muestra los SVG como <img> con CSP «default-src 'none'; sandbox»: scripts, fuentes e
    imágenes externas NO cargan. Un SVG que dependa de ellos se ve roto sin que nada avise.
  - prefers-reduced-motion: un SVG animado sin esa regla ignora la preferencia del lector.
  - alt en toda imagen: es el único texto que ve un lector de pantalla o un cliente sin imágenes.
  - Peso: el perfil lo abre mucha gente desde el móvil; una página pesada es una página lenta.
  - Los límites de CPU/memoria (<use> en cadena, desenfoques enormes) los frena esta puerta y no la CSP.

Cada problema lleva un identificador [regla]. tests/test_check.py exige al menos una mutación por
regla: añadir una regla sin su prueba hace fallar las pruebas.
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_SVG_KB = 60
MAX_PAGE_KB = 450  # suma de los SVG que carga UNA vista (escritorio, tableta o móvil)
MAX_README_KB = 100  # GitHub trunca el README a 500 KiB; esto es mucho menos
MAX_USE = 25  # <use> repetidos: una bomba exponencial cabe en 2 KB
MAX_BLUR = 20
MAX_SIDE = 2000
XMLNS_OK = {"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink"}
# Sitios que bloquean a clientes automáticos: se saltan en --links (no se pueden verificar con urllib)
BOT_BLOCKED = ("linkedin.com",)

RULES = {
    "svg-xml": "XML mal formado",
    "svg-root": "la raíz no es <svg>",
    "svg-viewbox": "sin viewBox",
    "svg-title": "sin <title> (texto alternativo)",
    "svg-size": f"pesa más de {MAX_SVG_KB} KB",
    "svg-tag": "etiqueta que no carga como <img> en GitHub o que ejecuta/consulta algo",
    "svg-href": "href que no es un fragmento #id",
    "svg-event": "atributo de evento on*",
    "svg-url": "url() que no es #id ni data:",
    "svg-import": "@import, image-set(), hoja de estilo externa, DOCTYPE/ENTITY o javascript:",
    "svg-css-escape": "barra invertida en el CSS (escapes para esconder url() o @import)",
    "svg-http": "URL http(s) dentro del SVG",
    "svg-motion": "animación sin prefers-reduced-motion",
    "svg-use": f"más de {MAX_USE} <use> (bomba de expansión)",
    "svg-dim": f"width/height de la raíz mayor que {MAX_SIDE}",
    "svg-blur": f"desenfoque (stdDeviation) mayor que {MAX_BLUR}",
    "svg-smil-href": "<set>/<animate> que cambia un href",
    "assets-empty": "assets/ no tiene SVG",
    "readme-missing": "README.md no existe",
    "readme-size": f"README.md pesa más de {MAX_README_KB} KB",
    "readme-generated": "README.md no declara que es generado",
    "readme-tag": "etiqueta prohibida en el README (script, iframe, style…)",
    "readme-md-image": "imagen con sintaxis Markdown ![](): no pasa por las reglas de <img>",
    "readme-noimg": "README.md no tiene imágenes",
    "img-alt": "imagen sin alt",
    "img-external": "imagen externa (servicio de terceros que puede caer)",
    "img-missing": "imagen que no existe",
    "img-location": "imagen fuera de assets/ o que no es .svg",
    "pic-incomplete": "<picture> sin <source> o sin <img>",
    "src-media": "<source> sin media",
    "src-missing": "<source> que apunta a un archivo inexistente",
    "link-scheme": "enlace con esquema distinto de https o mailto",
    "weight": f"una vista carga más de {MAX_PAGE_KB} KB de imágenes",
}


def fail(out: list[str], rule: str, msg: str) -> None:
    assert rule in RULES, f"regla desconocida {rule}"
    out.append(f"[{rule}] {msg}")


def _local(tag: str) -> str:
    return tag.split("}")[-1]


FORBIDDEN_TAGS = {"script", "foreignobject", "image", "iframe", "object", "embed", "audio", "video", "feimage", "link", "meta"}


def check_svg(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root)
    out: list[str] = []
    raw = path.read_bytes()
    if len(raw) > MAX_SVG_KB * 1024:
        fail(out, "svg-size", f"{rel}: {len(raw) / 1024:.1f} KB")
    text = raw.decode("utf-8", errors="replace")
    low = text.lower()
    try:
        tree = ET.fromstring(raw)
    except ET.ParseError as e:
        fail(out, "svg-xml", f"{rel}: {e}")
        return out
    if _local(tree.tag) != "svg":
        fail(out, "svg-root", str(rel))
    if "viewBox" not in tree.attrib:
        fail(out, "svg-viewbox", str(rel))
    if not any(_local(e.tag) == "title" and (e.text or "").strip() for e in tree.iter()):
        fail(out, "svg-title", str(rel))
    for dim in ("width", "height"):
        m = re.match(r"\s*([0-9.]+)", tree.attrib.get(dim, "0"))
        if m and float(m.group(1)) > MAX_SIDE:
            fail(out, "svg-dim", f"{rel}: {dim}={tree.attrib[dim]}")
    uses = 0
    for el in tree.iter():
        tag = _local(el.tag).lower()
        if tag in FORBIDDEN_TAGS:
            fail(out, "svg-tag", f"{rel}: <{tag}>")
        if tag == "use":
            uses += 1
        if tag in {"set", "animate"} and _local(el.attrib.get("attributeName", "")).lower() == "href":
            fail(out, "svg-smil-href", f"{rel}: <{tag}> sobre href")
        for k, v in el.attrib.items():
            key = _local(k).lower()
            if key == "href" and not v.startswith("#"):
                fail(out, "svg-href", f"{rel}: «{v[:60]}» en <{tag}>")
            if key.startswith("on"):
                fail(out, "svg-event", f"{rel}: {key} en <{tag}>")
            if key == "stdDeviation".lower():
                nums = [float(x) for x in re.findall(r"[0-9.]+", v)]
                if nums and max(nums) > MAX_BLUR:
                    fail(out, "svg-blur", f"{rel}: stdDeviation={v}")
    if uses > MAX_USE:
        fail(out, "svg-use", f"{rel}: {uses} <use>")
    for m in re.finditer(r"url\(\s*['\"]?([^)'\"]+)", text, flags=re.I):
        target = m.group(1).strip()
        if not (target.startswith("#") or target.lower().startswith("data:")):
            fail(out, "svg-url", f"{rel}: «{target[:60]}»")
    for needle in ("@import", "image-set(", "xml-stylesheet", "<!doctype", "<!entity", "javascript:", "-moz-binding", "expression("):
        if needle in low:
            fail(out, "svg-import", f"{rel}: contiene «{needle}»")
    for style in re.findall(r"<style[^>]*>(.*?)</style>", text, flags=re.S | re.I):
        if "\\" in style:
            fail(out, "svg-css-escape", str(rel))
            break
    for m in re.finditer(r"https?://[^\s\"'<>)]+", text, flags=re.I):
        if m.group(0) not in XMLNS_OK:
            fail(out, "svg-http", f"{rel}: «{m.group(0)[:60]}»")
    animated = "<animate" in low or "@keyframes" in low
    if animated and "prefers-reduced-motion" not in low:
        fail(out, "svg-motion", str(rel))
    return out


ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")


def _attrs(s: str) -> dict[str, str]:
    return {m.group(1).lower(): (m.group(2) or m.group(3) or m.group(4) or "") for m in ATTR.finditer(s)}


def _tags(html: str, name: str) -> list[dict[str, str]]:
    return [_attrs(m.group(1)) for m in re.finditer(rf"<{name}\b([^>]*)>", html, flags=re.I)]


def _pictures(html: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"<picture\b[^>]*>(.*?)</picture\s*>", html, flags=re.S | re.I)]


def _is_under_assets(root: Path, rel: str) -> bool:
    try:
        return (root / rel).resolve().relative_to((root / "assets").resolve()) is not None
    except ValueError:
        return False


def check_readme(root: Path) -> list[str]:
    out: list[str] = []
    readme = root / "README.md"
    if not readme.exists():
        fail(out, "readme-missing", "README.md")
        return out
    html = readme.read_text(encoding="utf-8")
    if len(html.encode()) > MAX_README_KB * 1024:
        fail(out, "readme-size", "README.md")
    if "Generado por scripts/generate.py" not in html:
        fail(out, "readme-generated", "se editaría a mano y se perdería al regenerar")
    if re.search(r"<\s*(script|iframe|object|embed|style|form|link|meta|base)\b", html, flags=re.I):
        fail(out, "readme-tag", "hay una etiqueta que GitHub quitaría o que no debería estar")
    if re.search(r"!\[[^\]]*\]\(", html):
        fail(out, "readme-md-image", "usar <img> con alt, para que pase por las reglas")
    imgs = _tags(html, "img")
    if not imgs:
        fail(out, "readme-noimg", "README.md")
    referenced: list[str] = []
    for im in imgs:
        src = im.get("src", "")
        if not im.get("alt", "").strip():
            fail(out, "img-alt", src)
        if re.match(r"(https?:)?//", src, flags=re.I):
            fail(out, "img-external", src)
            continue
        referenced.append(src)
    for inner in _pictures(html):
        sources = _tags(inner, "source")
        if not sources or not _tags(inner, "img"):
            fail(out, "pic-incomplete", "<picture> sin <source> o sin <img>")
        for s in sources:
            if "media" not in s:
                fail(out, "src-media", s.get("srcset", ""))
            referenced.append(s.get("srcset", ""))
    for rel in referenced:
        if not (root / rel).is_file():
            fail(out, "img-missing" if rel in {i.get("src") for i in imgs} else "src-missing", rel)
        elif not (rel.lower().endswith(".svg") and _is_under_assets(root, rel)):
            fail(out, "img-location", rel)
    for a in _tags(html, "a"):
        href = a.get("href", "")
        if not re.match(r"(https://|mailto:)", href, flags=re.I):
            fail(out, "link-scheme", href[:60])
    for msg in page_weight(html, root):
        fail(out, "weight", msg)
    return out


def page_weight(html: str, root: Path) -> list[str]:
    """Peso de lo que carga cada vista (d, t, m): las <img> sueltas más la variante que elige cada <picture>."""
    totals = {"d": 0, "t": 0, "m": 0}

    def size(rel: str) -> int:
        f = root / rel
        return f.stat().st_size if f.is_file() else 0

    outside = re.sub(r"<picture\b[^>]*>.*?</picture\s*>", "", html, flags=re.S | re.I)
    for im in _tags(outside, "img"):
        for k in totals:
            totals[k] += size(im.get("src", ""))
    for inner in _pictures(html):
        imgs, sources = _tags(inner, "img"), _tags(inner, "source")
        if not imgs:
            continue
        d = imgs[0].get("src", "")
        srcs = [s.get("srcset", "") for s in sources]
        totals["d"] += size(d)
        totals["t"] += size(srcs[1] if len(srcs) > 1 else (srcs[0] if srcs else d))
        totals["m"] += size(srcs[0] if srcs else d)
    names = {"d": "escritorio", "t": "tableta", "m": "móvil"}
    return [
        f"la vista de {names[k]} carga {v / 1024:.0f} KB (máximo {MAX_PAGE_KB})" for k, v in totals.items() if v > MAX_PAGE_KB * 1024
    ]


def check_links(root: Path) -> list[str]:
    out: list[str] = []
    html = (root / "README.md").read_text(encoding="utf-8")
    urls = sorted({a["href"] for a in _tags(html, "a") if a.get("href", "").startswith("https://")})
    for u in urls:
        if any(b in u for b in BOT_BLOCKED):
            print(f"  (salto {u}: bloquea clientes automáticos; verificar a mano)")
            continue
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (profile-check)"}, method="GET")
            with urllib.request.urlopen(req, timeout=25) as r:
                if r.status >= 400:
                    out.append(f"enlace roto ({r.status}): {u}")
        except urllib.error.HTTPError as e:
            out.append(f"enlace roto ({e.code}): {u}")
        except Exception as e:  # red caída, DNS, TLS…
            out.append(f"enlace inaccesible ({type(e).__name__}): {u}")
    return out


def run(root: Path, links: bool = False) -> list[str]:
    problems: list[str] = []
    svgs = sorted((root / "assets").rglob("*.svg"))
    if not svgs:
        fail(problems, "assets-empty", "assets/")
    seen = set(svgs)
    for s in svgs:
        problems += check_svg(s, root)
    # un SVG que el README cargue desde FUERA de assets/ también se revisa (y además se marca por su ubicación)
    html = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").exists() else ""
    extra = [i.get("src", "") for i in _tags(html, "img")] + [s.get("srcset", "") for inner in _pictures(html) for s in _tags(inner, "source")]
    for rel in extra:
        f = root / rel
        if rel.lower().endswith(".svg") and f.is_file() and f.resolve() not in {x.resolve() for x in seen}:
            problems += check_svg(f, root)
    problems += check_readme(root)
    if links:
        problems += check_links(root)
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--links", action="store_true")
    args = ap.parse_args()
    problems = run(Path(args.root), args.links)
    for p in problems:
        print("✗", p)
    n_svg = len(list((Path(args.root) / "assets").rglob("*.svg")))
    print(f"{'FALLA' if problems else 'OK'}: {n_svg} SVG, {len(problems)} problema(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
