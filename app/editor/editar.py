#!/usr/bin/env python3
"""Edita un video a partir de un plan (plan.json) y su transcripción.

Uso:
    python3 editar.py VIDEO transcripcion.json plan.json SALIDA.mp4 [--borrador]

Hace, en orden:
    1. Corta y reordena los fragmentos del plan (el gancho primero).
    2. Saca los silencios y muletillas largas dentro de cada fragmento (jump cuts).
    3. Lleva el video a vertical 1080x1920 (reel) o a pantalla doble.
    4. Quema subtítulos grandes con la palabra activa resaltada.
    5. Agrega los textos en pantalla y, en pantalla doble, los gráficos.
    6. Normaliza el volumen para redes (-14 LUFS).
Además deja SALIDA.srt con los subtítulos ya en los tiempos finales.

--borrador renderiza rápido y en baja resolución para revisar antes del final.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

W, H = 1080, 1920


# ---------- tiempos ----------

def palabras_en(palabras, s, e):
    """Palabras cuyo punto medio cae dentro de [s, e]."""
    return [w for w in palabras if s <= (w["s"] + w["e"]) / 2 <= e]


def piezas(plan, palabras):
    """Convierte los cortes del plan en piezas finales, sacando silencios internos."""
    gap = plan.get("recortar_silencios", 0.45)
    pad_in, pad_out = 0.08, 0.15
    out = []
    for c in plan["cortes"]:
        s, e = float(c["desde"]), float(c["hasta"])
        ws = palabras_en(palabras, s, e)
        if not ws:
            out.append((s, e))
            continue
        # ajustar bordes a la primera y última palabra
        s = max(s, ws[0]["s"] - pad_in)
        e = min(e, ws[-1]["e"] + pad_out)
        if not gap:
            out.append((s, e))
            continue
        ini = s
        for a, b in zip(ws, ws[1:]):
            if b["s"] - a["e"] > gap:
                out.append((ini, a["e"] + pad_out))
                ini = b["s"] - pad_in
        out.append((ini, e))
    return [(round(a, 3), round(b, 3)) for a, b in out if b - a > 0.12]


def remapear(palabras, pzs):
    """Lleva las palabras a la línea de tiempo final."""
    final, offset = [], 0.0
    for s, e in pzs:
        for w in palabras_en(palabras, s, e):
            final.append({"w": w["w"],
                          "s": max(0.0, w["s"] - s) + offset,
                          "e": min(e - s, w["e"] - s) + offset})
        offset += e - s
    return final, offset


# ---------- subtítulos ----------

def ass_color(hexcolor, alpha="00"):
    h = hexcolor.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha}{b}{g}{r}".upper()


def ass_t(t):
    t = max(0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def srt_t(t):
    ms = int(round(max(0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def limpiar(txt):
    return txt.replace("\\", "").replace("{", "(").replace("}", ")")


def bloques(final, por_linea, max_chars=20):
    out, cur = [], []
    for i, w in enumerate(final):
        if cur:
            prev = cur[-1]
            largo = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
            if (len(cur) >= por_linea or largo > max_chars
                    or prev["w"][-1:] in ".,?!;:" or w["s"] - prev["e"] > 0.6):
                out.append(cur)
                cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def armar_subs(plan, final, total, ruta_ass, ruta_srt):
    cfg = plan.get("subtitulos", {})
    doble = plan.get("formato") == "doble"
    color = cfg.get("color", "#FFFFFF")
    resalt = cfg.get("resaltado", "#FFD400")
    mayus = cfg.get("mayusculas", False)
    tam = cfg.get("tamano", 78)
    fuente = cfg.get("fuente", "Arial")

    # Sub: abajo en reel; en el medio (la unión) en pantalla doble.
    sub_align, sub_mv = (5, 0) if doble else (2, 430)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{fuente},{tam},{ass_color(color)},{ass_color(color)},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,{sub_align},60,60,{sub_mv},1
Style: Titulo,{fuente},66,&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,230,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev, srt = [], []
    if cfg.get("activar", True):
        bl = bloques(final, cfg.get("palabras_por_linea", 3))
        for k, b in enumerate(bl):
            fin_b = b[-1]["e"] + 0.25
            if k + 1 < len(bl):
                fin_b = min(fin_b, bl[k + 1][0]["s"])
            txts = [limpiar(w["w"].upper() if mayus else w["w"]) for w in b]
            srt.append((b[0]["s"], fin_b, " ".join(txts)))
            for i, w in enumerate(b):
                ini = b[0]["s"] if i == 0 else w["s"]
                fin = b[i + 1]["s"] if i + 1 < len(b) else fin_b
                if fin - ini < 0.04:
                    continue
                partes = [(f"{{\\c{ass_color(resalt)}}}{t}{{\\c{ass_color(color)}}}" if j == i else t)
                          for j, t in enumerate(txts)]
                ev.append(f"Dialogue: 1,{ass_t(ini)},{ass_t(fin)},Sub,,0,0,0,,{' '.join(partes)}")

    for t in plan.get("textos", []):
        tag = "{\\an5}" if t.get("posicion") == "centro" else ""
        fin = min(float(t["hasta"]), total)
        ev.append(f"Dialogue: 2,{ass_t(float(t['desde']))},{ass_t(fin)},Titulo,,0,0,0,,{tag}{limpiar(t['texto'])}")

    with open(ruta_ass, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(ev) + "\n")
    with open(ruta_srt, "w", encoding="utf-8") as f:
        for n, (a, b, t) in enumerate(srt, 1):
            f.write(f"{n}\n{srt_t(a)} --> {srt_t(b)}\n{t}\n\n")


# ---------- render ----------

def render(video, plan, pzs, total, ass_name, salida, workdir, borrador, plan_dir):
    doble = plan.get("formato") == "doble"
    x = float(plan.get("encuadre_x", 0.5))
    graficos = plan.get("graficos", []) if doble else []

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video]
    for g in graficos:
        cmd += ["-i", os.path.join(plan_dir, g["imagen"])]

    f = []
    for k, (s, e) in enumerate(pzs):
        f.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{k}]")
        f.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{k}]")
    f.append("".join(f"[v{k}][a{k}]" for k in range(len(pzs))) + f"concat=n={len(pzs)}:v=1:a=1[vc][ac]")

    if doble:
        f.append(f"[vc]scale={W}:{H//2}:force_original_aspect_ratio=increase,"
                 f"crop={W}:{H//2}:(in_w-{W})*{x}:(in_h-{H//2})/2,setsar=1,fps=30,"
                 f"pad={W}:{H}:0:{H//2}:color=0x111111[b0]")
        last = "b0"
        for j, g in enumerate(graficos, start=1):
            f.append(f"[{j}:v]scale={W}:{H//2}:force_original_aspect_ratio=decrease,"
                     f"pad={W}:{H//2}:(ow-iw)/2:(oh-ih)/2:color=0x111111,setsar=1[g{j}]")
            f.append(f"[{last}][g{j}]overlay=0:0:enable='between(t,{float(g['desde'])},{float(g['hasta'])})'[b{j}]")
            last = f"b{j}"
    else:
        f.append(f"[vc]scale={W}:{H}:force_original_aspect_ratio=increase,"
                 f"crop={W}:{H}:(in_w-{W})*{x}:(in_h-{H})/2,setsar=1,fps=30[b0]")
        last = "b0"

    # b-roll: imágenes (con zoom lento) o clips de video a pantalla completa,
    # por encima del video y por debajo de los subtítulos.
    n_in = 1 + len(graficos)
    for j, b in enumerate([b for b in plan.get("broll", []) if b.get("imagen") or b.get("video")]):
        ini, fin = float(b["desde"]), min(float(b["hasta"]), total)
        dur = max(0.3, fin - ini)
        ruta = os.path.join(plan_dir, b.get("video") or b["imagen"])
        if b.get("video"):
            cmd += ["-stream_loop", "-1", "-t", f"{dur:.3f}", "-i", ruta]
            mov = ""
        else:
            cmd += ["-loop", "1", "-framerate", "30", "-t", f"{dur:.3f}", "-i", ruta]
            # Ken Burns: zoom del 100 % al 110 % durante el plano
            mov = (f"scale=w='trunc({W}*1.1*(1+0.1*t/{dur:.3f})/2)*2':h=-2:eval=frame,"
                   f"crop={W}:{H},")
        f.append(f"[{n_in}:v]scale={int(W*1.1)}:{int(H*1.1)}:force_original_aspect_ratio=increase,"
                 f"crop={int(W*1.1)}:{int(H*1.1)},{mov}scale={W}:{H},setsar=1,fps=30,"
                 f"format=yuva420p,fade=in:st=0:d=0.15:alpha=1,"
                 f"setpts=PTS-STARTPTS+{ini:.3f}/TB[r{j}]")
        f.append(f"[{last}][r{j}]overlay=0:0:eof_action=pass:enable='between(t,{ini:.3f},{fin:.3f})'[br{j}]")
        last = f"br{j}"
        n_in += 1

    escala = ",scale=540:960" if borrador else ""
    f.append(f"[{last}]ass={ass_name}{escala}[vout]")
    f.append("[ac]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

    cmd += ["-filter_complex", ";".join(f), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "ultrafast" if borrador else "medium",
            "-crf", "28" if borrador else "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
            os.path.abspath(salida)]
    subprocess.run(cmd, check=True, cwd=workdir)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("transcripcion")
    p.add_argument("plan")
    p.add_argument("salida")
    p.add_argument("--borrador", action="store_true")
    a = p.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("Falta ffmpeg. Mac: brew install ffmpeg · Windows: winget install ffmpeg")

    with open(a.transcripcion, encoding="utf-8") as fh:
        tr = json.load(fh)
    with open(a.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
    if not plan.get("cortes"):
        sys.exit("El plan no tiene cortes.")

    pzs = piezas(plan, tr["palabras"])
    final, total = remapear(tr["palabras"], pzs)

    workdir = os.path.dirname(os.path.abspath(a.salida)) or "."
    base = os.path.splitext(os.path.basename(a.salida))[0]
    ass_name = f"{base}.ass"
    armar_subs(plan, final, total, os.path.join(workdir, ass_name),
               os.path.join(workdir, f"{base}.srt"))

    print(f"{len(plan['cortes'])} cortes del plan -> {len(pzs)} tomas sin silencios. "
          f"Duración final: {total:.1f} s")
    plan_dir = os.path.dirname(os.path.abspath(a.plan))
    print("Renderizando..." + (" (borrador)" if a.borrador else ""))
    render(os.path.abspath(a.video), plan, pzs, total, ass_name, a.salida, workdir, a.borrador, plan_dir)
    print(f"Listo: {a.salida}")


if __name__ == "__main__":
    main()
