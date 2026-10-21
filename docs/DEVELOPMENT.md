# Cómo se mantiene este perfil

`README.md` y `assets/*.svg` son **generados**: no se editan a mano. La fuente es `profile.toml`
(más `data/repos.json`, que baja `scripts/fetch_repos.py`). CI regenera y compara: una edición a
mano falla.

```bash
python3 -m venv .venv && .venv/bin/pip install --require-hashes -r scripts/requirements.txt
python3 scripts/fetch_repos.py          # datos públicos de los repos → data/repos.json
.venv/bin/python scripts/generate.py    # profile.toml + data/ → assets/*.svg y README.md
python3 scripts/check.py                # puerta de calidad (añade --links para comprobar enlaces)
python3 -m unittest discover tests -v   # la puerta, probada por mutación (una mutación por regla)
```

## Reglas de diseño (medidas, no supuestas)

- GitHub carga los SVG como `<img>` con `Content-Security-Policy: default-src 'none'; sandbox`:
  nada de scripts, fuentes ni imágenes externas. La tipografía va incrustada (base64) y recortada
  a los glifos que se usan; el texto pequeño usa la sans del sistema.
- **El ancho útil del README no es el del viewport.** Medido en github.com: viewport − 82 px
  (< 768), viewport − 370 (768–1011) y viewport − 434 (≥ 1012). Por eso cada pieza tiene tres
  variantes: `-d` (840 px), `-t` (600) y `-m` (360), y el README elige con
  `<picture><source media>` (cortes en `scripts/generate.py`: `MEDIA_M`, `MEDIA_T`). Con ese reparto
  toda variante se ve entre 0,75× y 1,1× de su tamaño de diseño, en cualquier ancho (comprobado de
  360 a 1440 px).
- Las tarjetas son opacas (azul noche): un SVG dentro de `<img>` sigue el tema del sistema operativo,
  no el de GitHub, así que no se puede depender de un fondo transparente.
- Solo dos piezas se mueven en bucle (cabecera y pipeline): cada animación infinita cuesta hilo
  principal. El resto es estático.
- `prefers-reduced-motion`: las animaciones CSS se apagan con la regla; SMIL no obedece a CSS, por eso
  las partículas tienen una capa gemela estática (`.m` se oculta, `.s` aparece). Se comprueba con el
  flag real de Chrome (`--force-prefers-reduced-motion`); la emulación de Playwright no llega a los
  SVG dentro de `<img>`.
- La generación es determinista (se verificó con Python 3.12 y 3.14 y misma salida byte a byte);
  si deja de serlo, el paso «regenerar y comparar» de CI lo delata.

## Contenido

Solo entra lo que tiene respaldo: un repo público, la web personal o el sitio del Laboratorio ADA.
Nada de cifras internas de las bases de datos del proyecto, ni nombres de servidores. Los íconos del
Toolbox son tecnologías que aparecen en repos propios, en el sitio ADA o en la web personal.
