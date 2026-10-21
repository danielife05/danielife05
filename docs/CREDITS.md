# Créditos y licencias

Todo lo que no es código propio entra por licencias que lo permiten, y queda acreditado aquí.

| Qué | De dónde | Licencia | Dónde está |
|---|---|---|---|
| Tipografía **Martian Mono SemiCondensed** (Regular y Bold) | [evilmartians/mono](https://github.com/evilmartians/mono), © The Martian Mono Project Authors | SIL OFL 1.1 | `scripts/fonts/` (con `OFL.txt`); un subconjunto de glifos va incrustado en cada SVG |
| Íconos de tecnologías (Python, C, C++, JavaScript, TypeScript, Kotlin, pandas, Hugging Face, Jupyter, FastAPI, React, Astro, MongoDB, PostgreSQL, MySQL, Docker, Linux, Git, GitHub) | [simple-icons](https://github.com/simple-icons/simple-icons) v16.35.0 | CC0 1.0 | `scripts/icons/si/` |
| Íconos de Java y AWS | [devicon](https://github.com/devicons/devicon) | MIT, © konpa | `scripts/icons/devicon/` |
| Íconos de línea de los nodos del pipeline y de los logros, y todo el diseño de las piezas | propio | — | `scripts/generate.py` |

Los logotipos son marcas de sus respectivos dueños y se muestran solo para indicar tecnologías que
uso. Se recolorean (GitHub, pandas, Python, C++, MySQL, PostgreSQL) únicamente para que no se
pierdan sobre el fondo azul noche.

## Técnicas tomadas de proyectos abiertos (sin copiar su arte)

- Texto que se tipea con `clip-path` y `steps()` dentro de un SVG, y que rota entre frases: la
  idea que popularizó [readme-typing-svg](https://github.com/DenverCoder1/readme-typing-svg) (MIT).
  Aquí se genera sin servicio externo, para que el perfil no se rompa si una instancia pública cae.
- Partículas con `animateMotion` + `mpath` y capas gemelas para `prefers-reduced-motion`
  (SMIL no obedece a la regla CSS): probado en Chrome real, ver la bitácora en el historial del repo.

## Lo que se decidió NO usar, y por qué

- **Serpiente de contribuciones y Pac-Man** (`Platane/snk`, `abozanona/pacman-contribution-graph`):
  no declaran licencia en su repositorio, y sobre un gráfico con pocas contribuciones exponen el
  vacío en vez de taparlo.
- **Tarjetas públicas de estadísticas** (`github-readme-stats`, `streak-stats`, contadores de
  visitas): con la actividad actual muestran rango bajo, racha 0 y contador 0, y dependen de
  instancias públicas que se caen. La tarjeta de repos por lenguaje es propia y se regenera con una
  Action usando solo el `GITHUB_TOKEN` de la ejecución.
