#!/usr/bin/env python3
"""Busca videos de stock verticales en Pexels para el b-roll del plan. Gratis.

Uso:
    python3 buscar_broll.py plan.json

Cada entrada de "broll" sin "imagen" ni "video" se busca en Pexels con su "busqueda"
(o, si no tiene, con su "prompt"), se descarga al lado del plan (broll-1.mp4...) y el plan
se actualiza solo con el video y el crédito del autor. También deja creditos-pexels.txt.

Clave: PEXELS_API_KEY (gratis en https://www.pexels.com/api/). Límite: 200 búsquedas por hora.
Pexels pide mencionarlo y, cuando se pueda, al autor: los créditos quedan listos para la descripción.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.pexels.com/v1/videos/search"
UA = "editor-de-video (https://github.com/Juampii01/editor-de-video)"
VACIAS = {"a", "an", "the", "of", "on", "in", "with", "and", "at", "to", "for", "their", "his", "her",
          "its", "from", "by", "as", "while", "through", "into", "is", "are", "close-up", "closeup",
          "shot", "cinematic", "dim", "late", "evening", "night"}


def pedir(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        return urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            sys.exit("Pexels rechazó la clave. Revisá PEXELS_API_KEY.")
        if e.code == 429:
            sys.exit("Llegaste al límite de búsquedas de Pexels (200 por hora). Probá más tarde.")
        sys.exit(f"Pexels respondió {e.code}.")
    except urllib.error.URLError as e:
        sys.exit(f"No hay conexión con Pexels ({e.reason}).")


def busqueda_de(b):
    if b.get("busqueda"):
        return b["busqueda"]
    # Sin búsqueda: palabras clave del prompt (los prompts largos no encuentran nada en stock).
    palabras = [w for w in re.findall(r"[a-zA-Z]+", b.get("prompt", "").lower()) if w not in VACIAS]
    return " ".join(palabras[:4])


def elegir_archivo(video):
    """El MP4 vertical más chico que cubra 1080x1920; si no hay, el más grande."""
    fs = [f for f in video.get("video_files", [])
          if f.get("file_type") == "video/mp4" and f.get("height") and f.get("width")
          and f["height"] >= f["width"]]
    if not fs:
        return None
    grandes = [f for f in fs if f["height"] >= 1920]
    return min(grandes, key=lambda f: f["height"]) if grandes else max(fs, key=lambda f: f["height"])


def buscar(clave, consulta, minimo, usados):
    q = urllib.parse.urlencode({"query": consulta, "orientation": "portrait", "per_page": 15})
    with pedir(f"{API}?{q}", {"Authorization": clave}) as r:
        data = json.load(r)
    for v in data.get("videos", []):
        if v["id"] in usados or v.get("duration", 0) < minimo:
            continue
        f = elegir_archivo(v)
        if f:
            return v, f
    return None, None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("plan")
    a = p.parse_args()

    clave = os.environ.get("PEXELS_API_KEY") or sys.exit(
        "Falta PEXELS_API_KEY. Es gratis: https://www.pexels.com/api/")
    with open(a.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    base = os.path.dirname(os.path.abspath(a.plan))
    pendientes = [b for b in plan.get("broll", []) if not b.get("imagen") and not b.get("video")]
    if not pendientes:
        print("No hay b-roll pendiente.")
        return

    usados = {b["credito"]["id"] for b in plan.get("broll", []) if b.get("credito", {}).get("id")}
    sin_resultado = []
    for n, b in enumerate(pendientes, 1):
        consulta = busqueda_de(b)
        minimo = max(1.0, float(b["hasta"]) - float(b["desde"]))
        print(f"[{n}/{len(pendientes)}] Pexels: {consulta}")
        v, f = buscar(clave, consulta, minimo, usados)
        if not v:
            sin_resultado.append(consulta)
            print("   sin resultados verticales; probá otra búsqueda")
            continue
        nombre = f"broll-{plan['broll'].index(b) + 1}.mp4"
        with pedir(f["link"]) as r, open(os.path.join(base, nombre), "wb") as out:
            while True:
                bloque = r.read(1 << 20)
                if not bloque:
                    break
                out.write(bloque)
        usados.add(v["id"])
        b["video"] = nombre
        b["credito"] = {"id": v["id"], "autor": v.get("user", {}).get("name", ""),
                        "autor_url": v.get("user", {}).get("url", ""), "url": v.get("url", "")}
        with open(a.plan, "w", encoding="utf-8") as fh:   # guarda en cada paso
            json.dump(plan, fh, ensure_ascii=False, indent=1)

    creditos = [b["credito"] for b in plan.get("broll", []) if b.get("credito")]
    if creditos:
        with open(os.path.join(base, "creditos-pexels.txt"), "w", encoding="utf-8") as fh:
            fh.write("Videos de Pexels:\n" + "".join(
                f"- {c['autor']}: {c['url']}\n" for c in creditos))
    if sin_resultado:
        print(f"Listo, pero sin resultados para: {', '.join(sin_resultado)}. Cambiá esas búsquedas y volvé a buscar.")
    else:
        print("Listo. Plan actualizado con los videos.")


if __name__ == "__main__":
    main()
