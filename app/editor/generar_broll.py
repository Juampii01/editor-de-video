#!/usr/bin/env python3
"""Genera las imágenes de b-roll que pide el plan, con la API que elija el usuario.

Uso:
    python3 generar_broll.py plan.json [--proveedor codex|openai|google] [--calidad low|medium|high]

Cada entrada de "broll" en el plan que tenga "prompt" y no tenga "imagen" se genera,
se guarda al lado del plan (broll-1.png, broll-2.png...) y el plan se actualiza solo.

Proveedores:
    codex            -> Codex CLI con la sesión de ChatGPT del usuario (codex login). Sin clave de API:
                        usa el plan de ChatGPT. Codex corta la generación en torno a 60 imágenes por día.
                        Ruta del programa: variable CODEX_BIN, o `codex` en el PATH, o la que trae la app ChatGPT.
Claves (cada usuario usa la suya, nada se guarda en el código):
    OPENAI_API_KEY   -> GPT Image   (modelo: variable OPENAI_IMAGE_MODEL, por defecto gpt-image-1)
    GEMINI_API_KEY   -> Nano Banana (modelo: variable GEMINI_IMAGE_MODEL, por defecto gemini-2.5-flash-image)
"""
import argparse
import base64
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ESTILO = ("Vertical 9:16 photo for a social media reel b-roll. Realistic, natural light, "
          "cinematic, shallow depth of field. No text, no captions, no watermarks, "
          "no readable brand logos. Scene: ")


def post(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"La API respondió {e.code}: {e.read().decode()[:500]}")


def openai_img(prompt, calidad):
    key = os.environ.get("OPENAI_API_KEY") or sys.exit("Falta OPENAI_API_KEY")
    model = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
    r = post("https://api.openai.com/v1/images/generations",
             {"model": model, "prompt": prompt, "size": "1024x1536", "quality": calidad, "n": 1},
             {"Authorization": f"Bearer {key}"})
    return base64.b64decode(r["data"][0]["b64_json"])


def google_img(prompt, calidad):
    key = os.environ.get("GEMINI_API_KEY") or sys.exit("Falta GEMINI_API_KEY")
    model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    r = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
             {"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"responseModalities": ["IMAGE"],
                                   "imageConfig": {"aspectRatio": "9:16"}}},
             {"x-goog-api-key": key})
    for part in r["candidates"][0]["content"]["parts"]:
        data = part.get("inlineData") or part.get("inline_data")
        if data:
            return base64.b64decode(data["data"])
    sys.exit("Nano Banana no devolvió imagen: " + json.dumps(r)[:400])


CODEX_APP = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"
CODEX_IMGS = os.path.join(os.path.expanduser("~"), ".codex", "generated_images")


def codex_bin():
    for c in (os.environ.get("CODEX_BIN"), shutil.which("codex"), CODEX_APP):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def codex_conectado():
    c = codex_bin()
    if not c:
        return False
    r = subprocess.run([c, "login", "status"], capture_output=True, text=True)
    return r.returncode == 0 and "logged in" in (r.stdout + r.stderr).lower()


def codex_img(prompt, calidad):
    """Le pide la imagen a Codex y la toma de ~/.codex/generated_images/<sesión>/."""
    c = codex_bin() or sys.exit("No se encontró Codex. Instalá la app de ChatGPT o Codex CLI y entrá con: codex login")
    pedido = ("Generate exactly ONE image with your image generation tool, vertical 9:16 (1024x1536). "
              "Do not write files, do not run commands, do not ask questions: just generate the image.\n\n" + prompt)
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([c, "exec", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
                            "-s", "read-only", "-C", d], input=pedido, capture_output=True, text=True, timeout=600)
    salida = r.stdout + r.stderr
    if re.search(r"usage limit|usage_limit_reached", salida, re.I):
        sys.exit("Codex llegó al límite de imágenes de tu plan por hoy. Probá mañana o usá una clave de API.")
    m = re.search(r"session id:\s*(\S+)", salida)
    pngs = sorted(glob.glob(os.path.join(CODEX_IMGS, m.group(1), "**", "*.png"), recursive=True),
                  key=os.path.getmtime) if m else []
    if not pngs:
        if "not logged in" in salida.lower() or "login" in salida.lower() and r.returncode:
            sys.exit("Codex no tiene sesión iniciada. Abrí una terminal y corré: codex login")
        sys.exit("Codex no generó la imagen: " + (salida.strip().splitlines() or ["sin respuesta"])[-1][:300])
    with open(pngs[-1], "rb") as fh:
        return fh.read()


PROVEEDORES = {"codex": codex_img, "openai": openai_img, "google": google_img}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("plan")
    p.add_argument("--proveedor", choices=PROVEEDORES, default=None)
    p.add_argument("--calidad", choices=["low", "medium", "high"], default="medium")
    a = p.parse_args()

    prov = a.proveedor or ("codex" if codex_conectado() else
                           "openai" if os.environ.get("OPENAI_API_KEY") else
                           "google" if os.environ.get("GEMINI_API_KEY") else None)
    if not prov:
        sys.exit("No hay cómo generar imágenes: iniciá sesión en Codex (codex login) "
                 "o definí OPENAI_API_KEY o GEMINI_API_KEY.")

    with open(a.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    base = os.path.dirname(os.path.abspath(a.plan))
    pendientes = [b for b in plan.get("broll", []) if b.get("prompt") and not b.get("imagen")
                  and not b.get("video")]
    if not pendientes:
        print("No hay b-roll pendiente de generar.")
        return

    for n, b in enumerate(pendientes, 1):
        nombre = f"broll-{plan['broll'].index(b) + 1}.png"
        print(f"[{n}/{len(pendientes)}] {prov}: {b['prompt'][:70]}...")
        img = PROVEEDORES[prov](ESTILO + b["prompt"], a.calidad)
        with open(os.path.join(base, nombre), "wb") as fh:
            fh.write(img)
        b["imagen"] = nombre
        with open(a.plan, "w", encoding="utf-8") as fh:   # guarda en cada paso
            json.dump(plan, fh, ensure_ascii=False, indent=1)
    print("Listo. Plan actualizado con las imágenes.")


if __name__ == "__main__":
    main()
