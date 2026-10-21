#!/usr/bin/env python3
"""Descarga la lista pública de repos de un usuario y la guarda en data/repos.json.

Solo biblioteca estándar. Usa GITHUB_TOKEN si existe (más cuota de peticiones); sin él también
funciona. Solo ve repos PÚBLICOS: es lo mismo que ve quien visita el perfil.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    user = tomllib.loads((ROOT / "profile.toml").read_text(encoding="utf-8"))["stats"]["user"]
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-readme-generator"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    repos, page = [], 1
    while True:
        req = urllib.request.Request(f"https://api.github.com/users/{user}/repos?type=owner&per_page=100&page={page}", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            batch = json.load(r)
        repos += [
            {"name": x["name"], "language": x["language"], "fork": x["fork"], "archived": x["archived"], "pushed_at": x["pushed_at"][:10]}
            for x in batch
            if not x["private"]
        ]
        if len(batch) < 100:
            break
        page += 1
    repos.sort(key=lambda x: x["name"].lower())
    target = ROOT / "data" / "repos.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")).get("repos") == repos:
        # Sin cambios: no se reescribe, así la fecha de «datos al» no se mueve y no hay commits vacíos cada semana.
        print(f"{len(repos)} repos públicos de {user}: sin cambios")
        return
    out = {"user": user, "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"), "repos": repos}
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(repos)} repos públicos de {user}: actualizado")


if __name__ == "__main__":
    sys.exit(main())
