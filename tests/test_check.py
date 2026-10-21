"""Pruebas de la puerta de calidad (scripts/check.py) por mutación.

Una puerta que nunca falla no prueba nada. Aquí se rompe a propósito una copia del perfil, una vez por
cada regla de check.RULES (y varias veces cuando hay maneras distintas de esquivarla), y se exige que
check.py (a) falle y (b) nombre la regla correcta. Además hay una prueba que obliga a que TODA regla
tenga su mutación: añadir una regla sin prueba hace fallar la suite.

    python3 -m unittest discover tests -v
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check  # noqa: E402

PAD = "x" * 58_000


def sub(old: str, new: str, count: int = 1):
    """Mutación de texto: reemplaza y exige que el texto original exista (si no, la prueba no prueba nada)."""

    def fn(s: str) -> str:
        assert old in s, f"el texto «{old[:50]}» no está: la mutación no aplica"
        return s.replace(old, new, count)

    return fn


def end_svg(inner: str):
    return sub("</svg>", inner + "</svg>")


def pad_comment(n: int = 70_000):
    return end_svg(f"<!--{'x' * n}-->")


# regla → lista de (archivo, función de mutación). Varias entradas = varias maneras de esquivar la regla.
MUTATIONS: dict[str, list[tuple[str, object]]] = {
    "svg-xml": [("assets/stats-d.svg", sub("</svg>", ""))],
    "svg-root": [("assets/sec-1-d.svg", lambda s: s.replace("<svg", "<g", 1).replace("</svg>", "</g>"))],
    "svg-viewbox": [("assets/sec-1-d.svg", lambda s: re.sub(r' viewBox="[^"]*"', "", s, count=1))],
    "svg-title": [("assets/sec-2-m.svg", lambda s: re.sub(r"<title[^>]*>.*?</title>", "", s))],
    "svg-size": [("assets/sec-1-d.svg", pad_comment())],
    "svg-tag": [
        ("assets/hero-d.svg", end_svg("<script>alert(1)</script>")),
        ("assets/hero-d.svg", end_svg('<image href="#x" width="1" height="1"/>')),
        ("assets/hero-d.svg", end_svg('<foreignObject width="1" height="1"/>')),
        ("assets/hero-d.svg", end_svg('<SCRIPT>alert(1)</SCRIPT>')),
        ("assets/hero-d.svg", end_svg('<filter id="f"><feImage href="#x"/></filter>')),
    ],
    "svg-href": [
        ("assets/hero-d.svg", end_svg('<a href="https://evil.example/x"><rect width="1" height="1"/></a>')),
        ("assets/hero-d.svg", end_svg('<a xlink:href="//evil.example/x"><rect width="1" height="1"/></a>')),
    ],
    "svg-event": [("assets/hero-d.svg", sub("<svg ", '<svg onload="alert(1)" '))],
    "svg-url": [("assets/skills-d.svg", sub("<style>", "<style>.x{background:url(//evil.example/p.png)}"))],
    "svg-import": [
        ("assets/skills-d.svg", sub("<style>", "<style>@import 'x.css';")),
        ("assets/skills-d.svg", sub("<style>", "<style>.x{background:image-set('//evil.example/p.png' 1x)}")),
        ("assets/skills-d.svg", lambda s: '<?xml-stylesheet href="//evil.example/s.css"?>' + s),
        ("assets/skills-d.svg", lambda s: '<!DOCTYPE svg [<!ENTITY a "b">]>' + s),
        ("assets/skills-d.svg", end_svg("<desc>javascript:alert(1)</desc>")),
    ],
    "svg-css-escape": [
        ("assets/skills-d.svg", sub("<style>", "<style>.x{background:u\\72l(//evil.example/p.png)}")),
        ("assets/skills-d.svg", sub("<style>", "<style>@\\69mport 'x.css';")),
    ],
    "svg-http": [("assets/hero-d.svg", end_svg("<text>https://evil.example/x</text>"))],
    "svg-motion": [("assets/pipeline-d.svg", sub("prefers-reduced-motion", "prefers-color-scheme"))],
    "svg-use": [("assets/pipeline-d.svg", end_svg('<use href="#main"/>' * 30))],
    "svg-dim": [("assets/sec-1-d.svg", sub('width="840"', 'width="1000000"'))],
    "svg-blur": [("assets/hero-d.svg", end_svg('<filter id="f"><feGaussianBlur stdDeviation="5000"/></filter>'))],
    "svg-smil-href": [("assets/hero-d.svg", end_svg('<a href="#x"><set attributeName="href" to="#y"/></a>'))],
    "readme-size": [("README.md", lambda s: s + "<!--" + "x" * 110_000 + "-->")],
    "readme-generated": [("README.md", sub("<!-- Generado por scripts/generate.py desde profile.toml: no editar a mano. -->", ""))],
    "readme-tag": [
        ("README.md", lambda s: s + '<iframe src="https://evil.example"></iframe>'),
        ("README.md", lambda s: s + "<SCRIPT>alert(1)</SCRIPT>"),
        ("README.md", lambda s: s + "<style>img{display:none}</style>"),
    ],
    "readme-md-image": [("README.md", lambda s: s + "\n![x](assets/hero-d.svg)\n")],
    "readme-noimg": [("README.md", lambda s: re.sub(r"<img\b", "<span", s, flags=re.I))],
    "img-alt": [
        ("README.md", sub('alt="Email"', 'alt=""')),
        ("README.md", lambda s: s + '<IMG SRC=assets/contact-email.svg WIDTH=1>'),
        ("README.md", lambda s: s + "<img src='assets/contact-email.svg' alt='   '>"),
    ],
    "img-external": [
        ("README.md", sub('src="assets/contact-email.svg"', 'src="https://img.shields.io/badge/x-y-green"')),
        ("README.md", lambda s: s + '<IMG SRC=https://evil.example/x.png ALT="x">'),
        ("README.md", lambda s: s + '<img src="//evil.example/x.png" alt="x">'),
    ],
    "img-missing": [("README.md", sub("assets/project-1.svg", "assets/no-existe.svg"))],
    "img-location": [
        ("README.md", lambda s: s + '<img src="README.md" alt="x">'),
    ],
    "pic-incomplete": [("README.md", lambda s: re.sub(r"<source\b[^>]*>", "", s, count=2))],
    "src-media": [("README.md", lambda s: re.sub(r' media="[^"]*"', "", s, count=1))],
    "src-missing": [("README.md", sub('srcset="assets/hero-m.svg"', 'srcset="assets/nada.svg"'))],
    "link-scheme": [
        ("README.md", sub('href="mailto:', 'href="javascript:alert(1)//')),
        ("README.md", lambda s: s + '<A HREF=javascript:alert(1)>x</A>'),
        ("README.md", lambda s: s + '<a href="http://insecure.example">x</a>'),
    ],
}
# reglas cuya mutación toca varios archivos a la vez o no es de texto: se aplican a mano en su prueba
SPECIAL = {"assets-empty", "readme-missing", "weight"}


class Gate(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="profile-check-"))
        shutil.copytree(ROOT / "assets", self.tmp / "assets")
        shutil.copy(ROOT / "README.md", self.tmp / "README.md")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def edit(self, rel: str, fn) -> None:
        f = self.tmp / rel
        old = f.read_text(encoding="utf-8")
        new = fn(old)
        self.assertNotEqual(new, old, "la mutación no cambió nada: la prueba no prueba nada")
        f.write_text(new, encoding="utf-8")

    def rules_hit(self) -> set[str]:
        return {m[1 : m.index("]")] for m in check.run(self.tmp)}

    def test_baseline_pasa(self) -> None:
        self.assertEqual(check.run(self.tmp), [])

    def test_toda_regla_tiene_su_mutacion(self) -> None:
        self.assertEqual(set(MUTATIONS) | SPECIAL, set(check.RULES), "hay reglas sin prueba, o pruebas de reglas que ya no existen")

    def test_cada_mutacion_dispara_su_regla(self) -> None:
        for rule, muts in MUTATIONS.items():
            for i, (rel, fn) in enumerate(muts):
                with self.subTest(rule=rule, variante=i):
                    # copia limpia para cada variante: una mutación no contamina a la siguiente
                    shutil.rmtree(self.tmp / "assets")
                    shutil.copytree(ROOT / "assets", self.tmp / "assets")
                    shutil.copy(ROOT / "README.md", self.tmp / "README.md")
                    self.edit(rel, fn)
                    hit = self.rules_hit()
                    self.assertIn(rule, hit, f"la puerta dejó pasar la mutación de «{rule}» (variante {i}); reglas disparadas: {sorted(hit)}")

    def test_peso_de_la_vista(self) -> None:
        # cada SVG por debajo de su tope individual, pero juntos una vista de escritorio pasa del presupuesto:
        # hace falta tocar varios archivos a la vez, por eso no cabe en la tabla de mutaciones
        for name in ["hero-d", "pipeline-d", "skills-d", "stats-d", "achievements-d", "sec-1-d", "sec-2-d", "sec-3-d", "sec-4-d"]:
            self.edit(f"assets/{name}.svg", pad_comment(52_000))
        hit = self.rules_hit()
        self.assertIn("weight", hit)

    def test_assets_vacio(self) -> None:
        shutil.rmtree(self.tmp / "assets")
        (self.tmp / "assets").mkdir()
        self.assertIn("assets-empty", self.rules_hit())

    def test_readme_ausente(self) -> None:
        (self.tmp / "README.md").unlink()
        self.assertIn("readme-missing", self.rules_hit())

    def test_svg_malicioso_fuera_de_assets_se_revisa(self) -> None:
        # un SVG con <script> fuera de assets/ pero cargado por el README no debe colarse
        (self.tmp / "otro").mkdir()
        (self.tmp / "otro" / "x.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><title>x</title><script>alert(1)</script></svg>', encoding="utf-8"
        )
        self.edit("README.md", lambda s: s + '<img src="otro/x.svg" alt="x">')
        hit = self.rules_hit()
        self.assertIn("svg-tag", hit)
        self.assertIn("img-location", hit)

    def test_picture_sin_source_no_revienta(self) -> None:
        # antes: IndexError en el cálculo de peso y la regla nunca imprimía su mensaje
        self.edit("README.md", lambda s: s + "<picture></picture>")
        self.assertIn("pic-incomplete", self.rules_hit())

    def test_cli_codigo_de_salida(self) -> None:
        ok = subprocess.run([sys.executable, str(ROOT / "scripts" / "check.py"), "--root", str(self.tmp)], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.edit("README.md", sub('alt="Email"', 'alt=""'))
        bad = subprocess.run([sys.executable, str(ROOT / "scripts" / "check.py"), "--root", str(self.tmp)], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("[img-alt]", bad.stdout)


if __name__ == "__main__":
    unittest.main()
