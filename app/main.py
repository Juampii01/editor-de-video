"""Editor de video: app web local.

Correr con:  .venv/bin/uvicorn app.main:app --port 8000
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(RAIZ, "app", "editor")
PROYECTOS = os.path.join(RAIZ, "proyectos")
ENV = os.path.join(RAIZ, ".env")
AJUSTES = os.path.join(RAIZ, "ajustes.json")
PY = sys.executable
CLAVES = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"]
EXT_VIDEO = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
EXT_IMG = {".png", ".jpg", ".jpeg", ".webp"}

sys.path.insert(0, SCRIPTS)
import editar  # noqa: E402  (piezas() es la misma lógica de silencios del render)

from . import chatgpt, ia  # noqa: E402

os.makedirs(PROYECTOS, exist_ok=True)
_locks = {}


# ---------- configuración (.env local) ----------

def leer_env():
    vals = {}
    if os.path.exists(ENV):
        for linea in open(ENV, encoding="utf-8"):
            if "=" in linea and not linea.lstrip().startswith("#"):
                k, v = linea.split("=", 1)
                vals[k.strip()] = v.strip().strip('"')
    return vals


for _k, _v in leer_env().items():
    os.environ.setdefault(_k, _v)

# El Python de python.org en Mac no trae certificados: sin esto falla la descarga del modelo.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass


def tiene_libass(binario):
    try:
        out = subprocess.run([binario, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        return any(l.split()[1:2] == ["ass"] for l in out.splitlines() if len(l.split()) > 1)
    except OSError:
        return False


def preparar_ffmpeg():
    """Los subtítulos necesitan un ffmpeg con libass. El ffmpeg de Homebrew ya no lo trae,
    ffmpeg-full sí (y queda aparte, sin pisar el otro). Lo ponemos primero en el PATH."""
    if shutil.which("ffmpeg") and tiene_libass("ffmpeg"):
        return True
    for d in ("/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin"):
        if os.path.exists(os.path.join(d, "ffmpeg")) and tiene_libass(os.path.join(d, "ffmpeg")):
            os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
            return True
    return False


# ---------- proyectos ----------

def ruta(pid, *partes):
    if not re.fullmatch(r"[a-z0-9-]+", pid):
        raise HTTPException(404, "Proyecto inexistente")
    base = os.path.join(PROYECTOS, pid)
    if not os.path.isdir(base):
        raise HTTPException(404, "Proyecto inexistente")
    return os.path.join(base, *partes)


def leer_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def escribir_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def estado(pid):
    return leer_json(ruta(pid, "estado.json"), {})


def guardar_estado(pid, **cambios):
    with _locks.setdefault(pid, threading.Lock()):
        e = estado(pid)
        e.update(cambios)
        escribir_json(ruta(pid, "estado.json"), e)
        return e


def video_de(pid):
    return ruta(pid, estado(pid)["video"])


def duracion(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", path],
                             capture_output=True, text=True, check=True).stdout
        return round(float(out), 2)
    except Exception:
        return None


# ---------- trabajos en segundo plano ----------

def trabajo(pid, tipo, fn):
    """Corre fn en un hilo. Un solo trabajo por proyecto a la vez."""
    t = estado(pid).get("trabajo")
    if t and t.get("estado") == "corriendo":
        raise HTTPException(409, f"Ya hay un trabajo en curso: {t['tipo']}")
    guardar_estado(pid, trabajo={"tipo": tipo, "estado": "corriendo", "log": "", "inicio": time.time()})

    def correr():
        try:
            fn()
            guardar_estado(pid, trabajo={**estado(pid)["trabajo"], "estado": "ok", "fin": time.time()})
        except Exception as e:  # el error se muestra en la interfaz
            msg = str(e) or e.__class__.__name__
            guardar_estado(pid, trabajo={**estado(pid)["trabajo"], "estado": "error",
                                         "error": msg, "fin": time.time()})

    threading.Thread(target=correr, daemon=True).start()


def ejecutar(pid, cmd):
    """Corre un script y va dejando la salida en el estado del proyecto."""
    proc = subprocess.Popen(cmd, cwd=ruta(pid), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    log = ""
    for linea in proc.stdout:
        log = (log + linea)[-4000:]
        guardar_estado(pid, trabajo={**estado(pid)["trabajo"], "log": log})
    if proc.wait() != 0:
        lineas = [l for l in log.strip().splitlines() if l.strip()]
        # Si hubo traceback, el mensaje útil (el de ffmpeg) es lo que se imprimió antes.
        tb = next((i for i, l in enumerate(lineas) if l.startswith("Traceback")), None)
        antes = lineas[:tb] if tb else []
        if antes and not antes[-1].startswith(("Renderizando", "Transcribiendo")):
            raise RuntimeError(antes[-1])
        raise RuntimeError(lineas[-1] if lineas else "El proceso falló")


# ---------- tiempos: original -> final ----------

def a_final(t, pzs):
    """Lleva un tiempo del original al video final (con silencios ya sacados)."""
    offset = 0.0
    for s, e in pzs:
        if s <= t <= e:
            return round(offset + t - s, 2)
        offset += e - s
    # cayó en un silencio recortado: tomar la pieza siguiente más cercana
    offset = 0.0
    mejor = None
    for s, e in pzs:
        d = abs(s - t)
        if mejor is None or d < mejor[0]:
            mejor = (d, offset)
        offset += e - s
    return round(mejor[1], 2) if mejor else 0.0


def plan_desde_ia(r, formato, palabras, previo=None):
    previo = previo or {}
    plan = {
        "formato": formato,
        "cortes": [{"desde": c["desde"], "hasta": c["hasta"], "nota": c["nota"]} for c in r["cortes"]],
        "recortar_silencios": previo.get("recortar_silencios", 0.45),
        "subtitulos": previo.get("subtitulos", {"activar": True, "color": "#FFFFFF", "resaltado": "#FFD400",
                                                "palabras_por_linea": 3, "mayusculas": False}),
        "encuadre_x": previo.get("encuadre_x", 0.5),
    }
    pzs = editar.piezas(plan, palabras)
    total = sum(e - s for s, e in pzs)

    def tramo(x):
        a = a_final(x["desde"], pzs)
        b = a_final(x["hasta"], pzs)
        if b <= a:
            b = min(total, a + 2.5)
        return {"desde": a, "hasta": round(b, 2)}

    plan["textos"] = [{**tramo(t), "texto": t["texto"], "posicion": t["posicion"]} for t in r["textos"]]
    plan["broll"] = [{**tramo(b), "prompt": b["prompt"]} for b in r["broll"]]
    plan["graficos"] = [{**tramo(g), "imagen": g["imagen"]} for g in r["graficos"]
                        if formato == "doble" and os.path.basename(g["imagen"]) == g["imagen"]]
    return plan


# ---------- app ----------

app = FastAPI(title="Editor de video")


# ----- cuenta de Anthropic -----
# Dos formas de conectarse: iniciar sesión con `ant auth login` (cuenta de Anthropic Console,
# sin pegar claves; el SDK lee esa sesión solo) o una clave de API en el .env.
# Nota: Anthropic no permite que apps de terceros usen el login de claude.ai (Pro/Max).

_sesion = {"ok": None, "cuando": 0.0, "detalle": ""}


def estado_anthropic(forzar=False):
    if not forzar and time.time() - _sesion["cuando"] < 60 and _sesion["ok"] is not None:
        return _sesion
    import anthropic
    try:
        anthropic.Anthropic(max_retries=0, timeout=15).models.list(limit=1)
        ok, detalle = True, ""
    except anthropic.AuthenticationError:
        ok, detalle = False, "La sesión venció o la clave no es válida."
    except anthropic.APIConnectionError:
        ok, detalle = False, "Sin conexión con Anthropic."
    except Exception as e:  # sin credenciales: el SDK no encuentra ni clave ni sesión
        ok, detalle = False, "" if "credential" in str(e).lower() or "api_key" in str(e).lower() else str(e)[:200]
    _sesion.update(ok=ok, cuando=time.time(), detalle=detalle)
    return _sesion


def modo_anthropic():
    return "clave" if os.environ.get("ANTHROPIC_API_KEY") else "sesion"


@app.get("/api/config")
def ver_config(forzar: bool = False):
    s = estado_anthropic(forzar)
    return {"claves": {k: bool(os.environ.get(k)) for k in CLAVES},
            "anthropic": {"conectado": s["ok"], "modo": modo_anthropic(), "detalle": s["detalle"],
                          "ant": bool(shutil.which("ant"))},
            "chatgpt": chatgpt.estado(),
            **motor(),
            "ffmpeg": bool(shutil.which("ffmpeg")),
            "libass": preparar_ffmpeg(),
            "modelo_descargado": os.path.isdir(os.path.expanduser("~/.cache/editor-de-video/parakeet-v3"))}


@app.post("/api/sesion/iniciar")
def iniciar_sesion():
    """Abre el navegador con el login de Anthropic Console (ant auth login)."""
    if not shutil.which("ant"):
        raise HTTPException(400, "Falta la herramienta ant. Instalala con: brew install anthropics/tap/ant")
    _sesion["cuando"] = 0
    if sys.platform == "darwin":
        # ant pide elegir organización y workspace: lo abrimos en una Terminal visible.
        subprocess.run(["osascript", "-e", 'tell application "Terminal" to activate',
                        "-e", 'tell application "Terminal" to do script "ant auth login && exit"'],
                       capture_output=True)
        return {"ok": True}
    raise HTTPException(400, "Abrí una terminal y corré: ant auth login")


@app.post("/api/sesion/cerrar")
def cerrar_sesion():
    if shutil.which("ant"):
        subprocess.run(["ant", "auth", "logout"], capture_output=True)
    _sesion["cuando"] = 0
    return ver_config(forzar=True)


# ----- motor para decidir los cortes: Claude o GPT (con el plan de ChatGPT) -----

def motor():
    a = leer_json(AJUSTES, {}) or {}
    return {"motor": a.get("motor", "claude"), "modelo": a.get("modelo_gpt")}


class Ajustes(BaseModel):
    motor: str | None = None
    modelo_gpt: str | None = None


@app.post("/api/ajustes")
def guardar_ajustes(a: Ajustes):
    actual = leer_json(AJUSTES, {}) or {}
    if a.motor is not None:
        if a.motor not in ("claude", "gpt"):
            raise HTTPException(400, "Motor inválido")
        actual["motor"] = a.motor
    if a.modelo_gpt is not None:
        actual["modelo_gpt"] = a.modelo_gpt
    escribir_json(AJUSTES, actual)
    return ver_config()


@app.get("/api/chatgpt/login")
def chatgpt_login(request: Request):
    # OpenAI exige un callback en 127.0.0.1 (no localhost); solo puede cambiar el puerto.
    puerto = request.url.port or 8000
    return RedirectResponse(chatgpt.url_login(f"http://127.0.0.1:{puerto}/api/chatgpt/callback"))


@app.get("/api/chatgpt/callback", response_class=HTMLResponse)
def chatgpt_callback(request: Request):
    try:
        chatgpt.completar_login(dict(request.query_params))
        a = leer_json(AJUSTES, {}) or {}
        if not a.get("modelo_gpt"):
            lista = chatgpt.modelos()
            if lista:
                a["modelo_gpt"] = lista[0]["slug"]
        a["motor"] = "gpt"
        escribir_json(AJUSTES, a)
        titulo, texto = "Listo", "Tu cuenta de ChatGPT quedó conectada. Ya podés cerrar esta pestaña y volver al editor."
    except chatgpt.ErrorChatGPT as e:
        titulo, texto = "No se pudo conectar", str(e)
    return f"""<!doctype html><meta charset="utf-8"><title>{titulo}</title>
<body style="font:15px system-ui;background:#0f1012;color:#ececf0;display:grid;place-items:center;height:100vh;margin:0">
<div style="max-width:420px;text-align:center"><h2>{titulo}</h2><p style="color:#9a9ca5">{texto}</p></div>
<script>setTimeout(() => window.close(), 2500)</script></body>"""


@app.post("/api/chatgpt/cerrar")
def chatgpt_cerrar():
    chatgpt.cerrar_sesion()
    return ver_config()


@app.get("/api/chatgpt/modelos")
def chatgpt_modelos():
    try:
        return chatgpt.modelos()
    except chatgpt.ErrorChatGPT as e:
        raise HTTPException(400, str(e))


class Config(BaseModel):
    claves: dict


@app.post("/api/config")
def guardar_config(c: Config):
    """Guarda claves en .env. Una clave vacía con valor null la borra."""
    vals = leer_env()
    for k, v in c.claves.items():
        if k not in CLAVES:
            continue
        if v is None:
            vals.pop(k, None)
            os.environ.pop(k, None)
        elif v.strip():
            vals[k] = v.strip()
            os.environ[k] = v.strip()
    with open(ENV, "w", encoding="utf-8") as fh:
        fh.writelines(f"{k}={v}\n" for k, v in vals.items())
    os.chmod(ENV, 0o600)
    return ver_config(forzar=True)


@app.get("/api/proyectos")
def listar():
    out = []
    for pid in os.listdir(PROYECTOS):
        e = leer_json(os.path.join(PROYECTOS, pid, "estado.json"))
        if e:
            out.append({"id": pid, "nombre": e["nombre"], "formato": e["formato"], "creado": e["creado"]})
    return sorted(out, key=lambda x: -x["creado"])


@app.post("/api/proyectos")
async def crear(video: UploadFile = File(...), formato: str = Form("reel"), cta: str = Form(""),
                notas: str = Form(""), imagenes: list[UploadFile] = File(default=[])):
    ext = os.path.splitext(video.filename or "")[1].lower()
    if ext not in EXT_VIDEO:
        raise HTTPException(400, "Formato de video no soportado")
    if formato not in ("reel", "doble", "recortes"):
        raise HTTPException(400, "Formato inválido")
    nombre = os.path.splitext(os.path.basename(video.filename))[0]
    slug = re.sub(r"[^a-z0-9]+", "-", nombre.lower()).strip("-")[:40] or "video"
    pid = f"{slug}-{uuid.uuid4().hex[:6]}"
    base = os.path.join(PROYECTOS, pid)
    os.makedirs(base)
    destino = os.path.join(base, "original" + ext)
    with open(destino, "wb") as fh:
        shutil.copyfileobj(video.file, fh, 1024 * 1024)
    escribir_json(os.path.join(base, "estado.json"), {
        "nombre": nombre, "formato": formato, "cta": cta, "notas": notas, "video": "original" + ext,
        "duracion": duracion(destino), "creado": time.time(), "piezas": [], "candidatos": [],
    })
    for img in imagenes:
        await _guardar_imagen(pid, img)
    _transcribir(pid)
    return {"id": pid}


def _transcribir(pid):
    trabajo(pid, "transcribir", lambda: ejecutar(
        pid, [PY, "-u", os.path.join(SCRIPTS, "transcribir.py"), video_de(pid), "--salida", ruta(pid)]))


@app.post("/api/proyectos/{pid}/transcribir")
def retranscribir(pid: str):
    _transcribir(pid)
    return {"ok": True}


@app.get("/api/proyectos/{pid}")
def ver(pid: str):
    e = estado(pid)
    tr = leer_json(ruta(pid, "transcripcion.json"))
    piezas = []
    for n in e.get("piezas", []):
        piezas.append({
            "n": n,
            "plan": leer_json(ruta(pid, f"plan-{n}.json")),
            "ia": leer_json(ruta(pid, f"plan-{n}.ia.json")),
            "borrador": os.path.exists(ruta(pid, f"borrador-{n}.mp4")),
            "final": os.path.exists(ruta(pid, f"final-{n}.mp4")),
        })
    imgs = sorted(f for f in os.listdir(ruta(pid)) if os.path.splitext(f)[1].lower() in EXT_IMG
                  and not f.startswith("frame"))
    return {"id": pid, **e, "transcripcion": tr and {"frases": tr["frases"], "palabras": tr["palabras"],
                                                     "idioma": tr.get("idioma")},
            "piezas": piezas, "imagenes": imgs}


async def _guardar_imagen(pid, img):
    ext = os.path.splitext(img.filename or "")[1].lower()
    if ext not in EXT_IMG:
        raise HTTPException(400, f"{img.filename}: solo PNG, JPG o WEBP")
    nombre = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(img.filename))
    with open(ruta(pid, nombre), "wb") as fh:
        shutil.copyfileobj(img.file, fh)
    return nombre


@app.post("/api/proyectos/{pid}/imagenes")
async def subir_imagenes(pid: str, imagenes: list[UploadFile] = File(...)):
    return {"imagenes": [await _guardar_imagen(pid, i) for i in imagenes]}


# ----- decisiones con Claude -----

def _requiere_transcripcion(pid):
    tr = leer_json(ruta(pid, "transcripcion.json"))
    if not tr:
        raise HTTPException(400, "Primero hay que transcribir el video")
    m = motor()
    if m["motor"] == "gpt":
        if not chatgpt.estado()["conectado"]:
            raise HTTPException(400, "Conectá tu cuenta de ChatGPT en Configuración.")
        if not m.get("modelo"):
            raise HTTPException(400, "Elegí un modelo de GPT en Configuración.")
    elif not estado_anthropic()["ok"]:
        raise HTTPException(400, "Conectá tu cuenta de Anthropic en Configuración.")
    return tr


@app.post("/api/proyectos/{pid}/candidatos")
def candidatos(pid: str):
    tr = _requiere_transcripcion(pid)
    e, m = estado(pid), motor()

    def fn():
        guardar_estado(pid, candidatos=ia.generar_candidatos(tr, e["cta"], e["notas"], motor=m))

    trabajo(pid, "candidatos", fn)
    return {"ok": True}


class Seleccion(BaseModel):
    indices: list[int]


@app.post("/api/proyectos/{pid}/piezas")
def crear_piezas(pid: str, sel: Seleccion):
    """Recortes de YouTube: arma un plan por cada candidato elegido."""
    tr = _requiere_transcripcion(pid)
    e = estado(pid)
    m = motor()
    elegidos = [e["candidatos"][i] for i in sel.indices if 0 <= i < len(e["candidatos"])]
    if not elegidos:
        raise HTTPException(400, "Elegí al menos un fragmento")

    def fn():
        piezas = list(e.get("piezas", []))
        for c in elegidos:
            n = max(piezas, default=0) + 1
            r = ia.generar_plan(tr, "reel", e["cta"], e["notas"], [], rango=(c["desde"], c["hasta"]),
                               motor=m)
            r["rango"] = [c["desde"], c["hasta"]]
            escribir_json(ruta(pid, f"plan-{n}.ia.json"), r)
            escribir_json(ruta(pid, f"plan-{n}.json"), plan_desde_ia(r, "reel", tr["palabras"]))
            piezas.append(n)
            guardar_estado(pid, piezas=piezas)

    trabajo(pid, "plan", fn)
    return {"ok": True}


class Pedido(BaseModel):
    indicaciones: str = ""


@app.post("/api/proyectos/{pid}/plan")
@app.post("/api/proyectos/{pid}/plan/{n}")
def generar_plan(pid: str, n: int | None = None, p: Pedido = Pedido()):
    """Crea el plan (o lo rehace con las indicaciones del usuario)."""
    tr = _requiere_transcripcion(pid)
    e = estado(pid)
    formato = "reel" if e["formato"] == "recortes" else e["formato"]
    n = n or 1
    previo_ia = leer_json(ruta(pid, f"plan-{n}.ia.json"))
    previo = leer_json(ruta(pid, f"plan-{n}.json"))
    imgs = ver(pid)["imagenes"]
    m = motor()

    def fn():
        rango = tuple(previo_ia["rango"]) if previo_ia and previo_ia.get("rango") else None
        r = ia.generar_plan(tr, formato, e["cta"], e["notas"], imgs, rango=rango,
                            plan_previo=previo_ia if p.indicaciones else None,
                            indicaciones=p.indicaciones, motor=m)
        if rango:
            r["rango"] = list(rango)
        escribir_json(ruta(pid, f"plan-{n}.ia.json"), r)
        escribir_json(ruta(pid, f"plan-{n}.json"), plan_desde_ia(r, formato, tr["palabras"], previo))
        piezas = estado(pid).get("piezas", [])
        if n not in piezas:
            guardar_estado(pid, piezas=sorted(piezas + [n]))

    trabajo(pid, "plan", fn)
    return {"ok": True}


@app.put("/api/proyectos/{pid}/plan/{n}")
def guardar_plan(pid: str, n: int, plan: dict):
    if n not in estado(pid).get("piezas", []):
        raise HTTPException(404, "Pieza inexistente")
    if not plan.get("cortes"):
        raise HTTPException(400, "El plan necesita al menos un corte")
    escribir_json(ruta(pid, f"plan-{n}.json"), plan)
    return {"ok": True, "duracion": duracion_plan(pid, plan)}


def duracion_plan(pid, plan):
    tr = leer_json(ruta(pid, "transcripcion.json"))
    return round(sum(e - s for s, e in editar.piezas(plan, tr["palabras"])), 1)


# ----- b-roll y render -----

@app.post("/api/proyectos/{pid}/broll/{n}")
def generar_broll(pid: str, n: int, calidad: str = "medium"):
    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        raise HTTPException(400, "Falta una clave de OpenAI o Gemini para generar imágenes.")
    if calidad not in ("low", "medium", "high"):
        raise HTTPException(400, "Calidad inválida")
    plan_path = ruta(pid, f"plan-{n}.json")
    trabajo(pid, "broll", lambda: ejecutar(
        pid, [PY, "-u", os.path.join(SCRIPTS, "generar_broll.py"), plan_path, "--calidad", calidad]))
    return {"ok": True}


@app.post("/api/proyectos/{pid}/render/{n}")
def render(pid: str, n: int, borrador: bool = True):
    if not os.path.exists(ruta(pid, f"plan-{n}.json")):
        raise HTTPException(404, "Pieza inexistente")
    if not preparar_ffmpeg():
        raise HTTPException(400, "Tu ffmpeg no puede quemar subtítulos (le falta libass). "
                                 "En Mac: brew install ffmpeg-full")
    salida = ruta(pid, f"{'borrador' if borrador else 'final'}-{n}.mp4")
    cmd = [PY, "-u", os.path.join(SCRIPTS, "editar.py"), video_de(pid), ruta(pid, "transcripcion.json"),
           ruta(pid, f"plan-{n}.json"), salida] + (["--borrador"] if borrador else [])
    trabajo(pid, "borrador" if borrador else "final", lambda: ejecutar(pid, cmd))
    return {"ok": True}


@app.get("/api/proyectos/{pid}/frame")
def frame(pid: str, t: float = 5.0):
    """Un fotograma del original, para elegir el encuadre."""
    t = max(0.0, min(t, (estado(pid).get("duracion") or 6) - 0.5))
    out = ruta(pid, "frame.jpg")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", video_de(pid),
                    "-frames:v", "1", "-vf", "scale=640:-2", out], check=True)
    return FileResponse(out, headers={"Cache-Control": "no-store"})


@app.get("/api/proyectos/{pid}/archivo/{nombre}")
def archivo(pid: str, nombre: str, descargar: bool = False):
    if os.path.basename(nombre) != nombre or nombre.startswith("."):
        raise HTTPException(404)
    path = ruta(pid, nombre)
    if not os.path.isfile(path):
        raise HTTPException(404)
    e = estado(pid)
    return FileResponse(path, filename=f"{e['nombre']}-{nombre}" if descargar else None,
                        headers={"Cache-Control": "no-store"})


@app.delete("/api/proyectos/{pid}")
def borrar(pid: str):
    """Borra la carpeta de trabajo de la app (nunca el video original del usuario)."""
    shutil.rmtree(ruta(pid))
    return {"ok": True}


app.mount("/", StaticFiles(directory=os.path.join(RAIZ, "app", "static"), html=True), name="static")
