#!/usr/bin/env python3
"""Transcribe un video con tiempos por palabra. Corre local y gratis.

Uso:
    python3 transcribir.py VIDEO [--salida carpeta] [--motor parakeet|whisper]

Motor por defecto: Parakeet v3 (NVIDIA, vía sherpa-onnx). Entiende español, inglés y otros
23 idiomas europeos sin configurar nada. La primera vez descarga el modelo (~490 MB) desde
GitHub y lo guarda en ~/.cache/editor-de-video. Requiere: pip install sherpa-onnx numpy

Motor alternativo: --motor whisper (pip install faster-whisper). Descarga desde HuggingFace.

Genera en la carpeta de salida (por defecto, al lado del video):
    transcripcion.json  -> palabras con inicio y fin, para editar.py
    transcripcion.txt   -> frases con tiempos, para que Claude decida los cortes
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request

MODELO_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
              "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2")
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "editor-de-video")
SR = 16000


def fmt(t):
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


def modelo_parakeet():
    destino = os.path.join(CACHE, "parakeet-v3")
    if glob.glob(os.path.join(destino, "*", "encoder.int8.onnx")):
        return glob.glob(os.path.join(destino, "*"))[0]
    os.makedirs(destino, exist_ok=True)
    print("Descargando el modelo de transcripción (~490 MB, solo la primera vez)...")
    tmp = os.path.join(destino, "modelo.tar.bz2")
    urllib.request.urlretrieve(MODELO_URL, tmp)
    print("Descomprimiendo...")
    with tarfile.open(tmp, "r:bz2") as t:
        t.extractall(destino, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(destino)
    os.remove(tmp)
    return glob.glob(os.path.join(destino, "*"))[0]


def audio_mono(video):
    import numpy as np
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-ac", "1", "-ar", str(SR),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768


def transcribir_parakeet(video):
    try:
        import numpy as np
        import sherpa_onnx
    except ImportError:
        sys.exit("Falta sherpa-onnx. Instalalo con: pip install sherpa-onnx numpy")
    m = modelo_parakeet()
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=os.path.join(m, "encoder.int8.onnx"), decoder=os.path.join(m, "decoder.int8.onnx"),
        joiner=os.path.join(m, "joiner.int8.onnx"), tokens=os.path.join(m, "tokens.txt"),
        model_type="nemo_transducer", num_threads=max(2, (os.cpu_count() or 4) - 1))
    a = audio_mono(video)
    palabras, pos, chunk = [], 0, 20 * SR
    while pos < len(a):
        end = min(len(a), pos + chunk)
        if end < len(a):  # cortar en el punto más silencioso de los últimos 2 s
            win = a[end - 2 * SR:end]
            energia = np.convolve(win ** 2, np.ones(800) / 800, "same")
            end = end - 2 * SR + int(np.argmin(energia))
        s = rec.create_stream()
        s.accept_waveform(SR, a[pos:end])
        rec.decode_stream(s)
        off, cur = pos / SR, None
        for tok, t in zip(s.result.tokens, s.result.timestamps):
            t += off
            if tok.startswith((" ", "▁")) or cur is None:
                if cur and cur["w"]:
                    palabras.append(cur)
                cur = {"w": tok.replace("▁", "").strip(), "s": t, "e": t + 0.12}
            else:
                cur["w"] += tok
                cur["e"] = t + 0.12
        if cur and cur["w"]:
            palabras.append(cur)
        pos = end
    for i in range(len(palabras) - 1):
        palabras[i]["e"] = min(max(palabras[i]["e"], palabras[i]["s"] + 0.12), palabras[i + 1]["s"])
    for p in palabras:
        p["s"], p["e"] = round(p["s"], 2), round(p["e"], 2)
    return palabras, "auto", len(a) / SR


def transcribir_whisper(video, idioma, modelo):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("Falta faster-whisper. Instalalo con: pip install faster-whisper")
    model = WhisperModel(modelo, device="auto", compute_type="int8")
    segs, info = model.transcribe(video, language=idioma, word_timestamps=True, vad_filter=True)
    palabras = [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)}
                for s in segs for w in (s.words or []) if w.word.strip()]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=nw=1:nk=1", video],
                               capture_output=True, text=True, check=True).stdout)
    return palabras, info.language, dur


def frases_de(palabras):
    fr, cur = [], []
    for p in palabras:
        cur.append(p)
        if p["w"][-1:] in ".?!," or len(cur) >= 16:
            fr.append({"s": cur[0]["s"], "e": cur[-1]["e"], "texto": " ".join(x["w"] for x in cur)})
            cur = []
    if cur:
        fr.append({"s": cur[0]["s"], "e": cur[-1]["e"], "texto": " ".join(x["w"] for x in cur)})
    return fr


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("--salida", default=None)
    p.add_argument("--motor", choices=["parakeet", "whisper"], default="parakeet")
    p.add_argument("--idioma", default=None, help="solo whisper: es, en...")
    p.add_argument("--modelo", default="small", help="solo whisper: tiny, base, small, medium")
    a = p.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("Falta ffmpeg. Mac: brew install ffmpeg · Windows: winget install ffmpeg")
    salida = a.salida or os.path.dirname(os.path.abspath(a.video))
    os.makedirs(salida, exist_ok=True)

    print(f"Transcribiendo con {a.motor}...")
    if a.motor == "parakeet":
        palabras, idioma, dur = transcribir_parakeet(a.video)
    else:
        palabras, idioma, dur = transcribir_whisper(a.video, a.idioma, a.modelo)
    frases = frases_de(palabras)

    data = {"video": os.path.abspath(a.video), "duracion": round(dur, 2), "idioma": idioma,
            "palabras": palabras, "frases": frases}
    with open(os.path.join(salida, "transcripcion.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    with open(os.path.join(salida, "transcripcion.txt"), "w", encoding="utf-8") as f:
        for fr in frases:
            f.write(f"[{fmt(fr['s'])} - {fmt(fr['e'])}] {fr['texto']}\n")
    print(f"Listo: {len(frases)} frases, {len(palabras)} palabras. Archivos en {salida}")


if __name__ == "__main__":
    main()
