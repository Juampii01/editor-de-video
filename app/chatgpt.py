"""Sign in with ChatGPT: el usuario usa su plan de ChatGPT (Plus/Pro) para que GPT decida los cortes.

Flujo para apps open source y locales (developers.openai.com/siwc/token-sharing-open-source):
registro dinámico con client_id=dynamic_agent_client, PKCE y callback en 127.0.0.1.
Con el plan solo se puede usar la Responses API (store=false, stream=true); la generación
de imágenes no está incluida, así que el b-roll sigue necesitando una clave de API.

Los tokens se guardan fuera del repo, en ~/.config/editor-de-video/ con permisos 0600.
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
import uuid

import httpx
import jwt
import openai

EMISOR = "https://auth.openai.com"
AUTORIZAR = f"{EMISOR}/api/accounts/authorize"
TOKEN = f"{EMISOR}/api/accounts/oauth/token"
JWKS = f"{EMISOR}/.well-known/jwks.json"
DESCUBRIMIENTO = f"{EMISOR}/.well-known/openid-configuration"
RECURSO = "https://api.openai.com/v1"
ALCANCE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
ALCANCE_PLAN = "chatgpt.tokens.use.direct"
NOMBRE_APP = "Editor de video"

DIR = os.path.join(os.path.expanduser("~"), ".config", "editor-de-video")
HOST = os.path.join(DIR, "chatgpt-host.json")
AUTH = os.path.join(DIR, "chatgpt-auth.json")

_pendientes = {}          # state -> datos del intento de login en curso
_lock = threading.Lock()  # serializa refrescos: el refresh token rota en cada uso


class ErrorChatGPT(Exception):
    pass


# ---------- almacenamiento ----------

def _leer(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _escribir(path, data):
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)


def _host_id():
    # OpenAI espera un URN: urn:uuid:<uuid>
    h = _leer(HOST) or {}
    hid = h.get("ext_agent_host_id") or str(uuid.uuid4())
    if not hid.startswith("urn:uuid:"):
        hid = f"urn:uuid:{hid}"
    if h.get("ext_agent_host_id") != hid:
        _escribir(HOST, {"ext_agent_host_id": hid})
    return hid


def _sesion():
    a = _leer(AUTH)
    return a if a and a.get("refresh_token") else None


def estado():
    a = _sesion()
    return {"conectado": bool(a), "email": a.get("email") if a else None}


# ---------- login ----------

def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def url_login(redirect_uri):
    """Arma la URL de autorización. Si ya hubo una registración, la reusa."""
    previo = _leer(AUTH) or {}
    verificador = _b64(secrets.token_bytes(32))
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    params = {
        "client_id": previo.get("client_id") or "dynamic_agent_client",
        "ext_agent_host_id": _host_id(),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": ALCANCE,
        "resource": RECURSO,
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64(hashlib.sha256(verificador.encode()).digest()),
        "code_challenge_method": "S256",
    }
    if previo.get("client_id"):
        if previo.get("email"):
            params["login_hint"] = previo["email"]
    else:
        params["agent_name_hint"] = NOMBRE_APP
    for k in [k for k, v in _pendientes.items() if time.time() - v["creado"] > 900]:
        _pendientes.pop(k, None)
    _pendientes[state] = {"verificador": verificador, "nonce": nonce, "redirect_uri": redirect_uri,
                          "client_id": previo.get("client_id"), "creado": time.time()}
    return f"{AUTORIZAR}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"


def completar_login(query):
    """Procesa el callback: valida, canjea el código, verifica la identidad y guarda la sesión."""
    p = _pendientes.pop(query.get("state", ""), None)
    if not p:
        raise ErrorChatGPT("El inicio de sesión expiró o no es válido. Probá de nuevo.")
    if query.get("error"):
        if query["error"] == "access_denied":
            raise ErrorChatGPT("Cancelaste el inicio de sesión.")
        raise ErrorChatGPT(f"ChatGPT respondió: {query.get('error_description') or query['error']}")
    client_id = p["client_id"]
    devuelto = query.get("client_id")
    if client_id and devuelto and devuelto != client_id:
        raise ErrorChatGPT("ChatGPT devolvió otra registración. Probá de nuevo.")
    client_id = client_id or devuelto
    if not client_id:
        raise ErrorChatGPT("La registración en ChatGPT quedó incompleta. Probá de nuevo.")
    if not p["client_id"]:  # guardar la registración antes de canjear el código
        _escribir(AUTH, {"client_id": client_id})

    r = httpx.post(TOKEN, data={"grant_type": "authorization_code", "client_id": client_id,
                                "code": query.get("code", ""), "code_verifier": p["verificador"],
                                "redirect_uri": p["redirect_uri"], "resource": RECURSO}, timeout=30)
    if r.status_code != 200:
        raise ErrorChatGPT("No se pudo completar el inicio de sesión. Probá de nuevo.")
    tok = r.json()

    try:
        clave = jwt.PyJWKClient(JWKS).get_signing_key_from_jwt(tok["id_token"])
        ident = jwt.decode(tok["id_token"], clave.key, algorithms=["RS256", "ES256"],
                           audience=client_id, issuer=EMISOR)
    except (jwt.PyJWTError, KeyError) as e:
        raise ErrorChatGPT(f"No se pudo verificar la identidad de ChatGPT ({e}).")
    if ident.get("nonce") != p["nonce"]:
        raise ErrorChatGPT("No se pudo verificar la identidad de ChatGPT (nonce).")

    previo = _leer(AUTH) or {}
    if previo.get("subject") and previo["subject"] != ident["sub"]:
        previo = {"client_id": client_id}  # otra cuenta: no mezclar datos
    if ALCANCE_PLAN not in tok.get("scope", "").split():
        raise ErrorChatGPT("No autorizaste usar tu plan de ChatGPT en esta app. "
                           "Volvé a iniciar sesión y aceptá el permiso de uso del plan.")
    _guardar_tokens({**previo, "client_id": client_id, "subject": ident["sub"],
                     "email": ident.get("email"), "issuer": EMISOR,
                     "ext_agent_host_id": _host_id(), "id_token": tok["id_token"]}, tok)


def _guardar_tokens(base, tok):
    _escribir(AUTH, {**base, "access_token": tok["access_token"],
                     "refresh_token": tok.get("refresh_token") or base.get("refresh_token"),
                     "token_type": tok.get("token_type", "Bearer"),
                     "scopes": tok.get("scope", base.get("scopes", "")),
                     "expira": time.time() + int(tok.get("expires_in", 3600)),
                     "saved_at": time.time()})


def _token():
    """Devuelve un access token vigente; lo refresca si vence en menos de 5 minutos."""
    with _lock:
        a = _sesion()
        if not a:
            raise ErrorChatGPT("Conectá tu cuenta de ChatGPT en Configuración.")
        if a.get("expira", 0) - time.time() > 300:
            return a["access_token"]
        r = httpx.post(TOKEN, data={"grant_type": "refresh_token", "client_id": a["client_id"],
                                    "refresh_token": a["refresh_token"], "resource": RECURSO}, timeout=30)
        if r.status_code != 200:
            if "invalid_grant" in r.text:
                _escribir(AUTH, {k: a[k] for k in ("client_id", "email", "subject") if k in a})
                raise ErrorChatGPT("Tu sesión de ChatGPT venció. Volvé a conectarte en Configuración.")
            raise ErrorChatGPT("No se pudo renovar la sesión de ChatGPT. Probá en un rato.")
        tok = r.json()
        _guardar_tokens(a, tok)
        return tok["access_token"]


def cerrar_sesion():
    """Revoca el refresh token y borra los tokens locales (la registración se conserva)."""
    a = _sesion()
    if not a:
        return
    try:
        rev = httpx.get(DESCUBRIMIENTO, timeout=10).json().get("revocation_endpoint")
        if rev:
            httpx.post(rev, data={"token": a["refresh_token"], "token_type_hint": "refresh_token",
                                  "client_id": a["client_id"]}, timeout=15)
    except httpx.HTTPError:
        pass  # se borran igual; el usuario puede desconectar la app desde ChatGPT
    _escribir(AUTH, {k: a[k] for k in ("client_id", "email", "subject") if k in a})


# ---------- modelos e inferencia ----------

def _cliente():
    return openai.OpenAI(api_key=_token(), base_url=RECURSO, max_retries=0, timeout=600)


def modelos():
    r = httpx.get(f"{RECURSO}/models", headers={"Authorization": f"Bearer {_token()}"}, timeout=30)
    if r.status_code != 200:
        raise ErrorChatGPT("No se pudo leer la lista de modelos de tu cuenta de ChatGPT.")
    return [{"slug": m["slug"], "nombre": m.get("display_name") or m["slug"]}
            for m in r.json().get("models", []) if m.get("visibility") == "list"]


ERRORES = {
    "subscription_sharing_usage_limit_exceeded": "Llegaste al límite de uso de tu plan de ChatGPT en esta app.",
    "subscription_sharing_usage_unavailable": "El uso de tu plan de ChatGPT no está disponible ahora.",
    "subscription_sharing_user_not_eligible": "Tu cuenta de ChatGPT no tiene habilitado usar el plan en otras apps.",
    "subscription_sharing_invalid_user": "Tu sesión de ChatGPT no es válida. Volvé a conectarte.",
}


def _codigo(e):
    body = getattr(e, "body", None)
    err = body.get("error", body) if isinstance(body, dict) else None
    return err.get("code") if isinstance(err, dict) else None


def pedir_json(modelo, instrucciones, usuario, esquema):
    """Pide a GPT una respuesta que cumpla el esquema. Si la salida estructurada no está
    disponible con el plan, lo pide en el prompt y valida las claves a mano."""
    pedido = dict(model=modelo, instructions=instrucciones,
                  input=[{"role": "user", "content": usuario}], store=False, stream=True)
    con_formato = {**pedido, "text": {"format": {"type": "json_schema", "name": "respuesta",
                                                 "schema": esquema, "strict": True}}}
    try:
        texto = _stream(con_formato)
    except openai.BadRequestError as e:
        if "format" not in str(e).lower() and "json_schema" not in str(e).lower():
            raise ErrorChatGPT(f"ChatGPT rechazó el pedido: {e.message}")
        pedido["instructions"] = (instrucciones + "\n\nRespondé SOLO con un objeto JSON que cumpla este "
                                  "esquema, sin texto alrededor ni bloques de código:\n" + json.dumps(esquema))
        try:
            texto = _stream(pedido)
        except openai.BadRequestError as e2:
            raise ErrorChatGPT(f"ChatGPT rechazó el pedido: {e2.message}")
    texto = texto.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(texto)
    except json.JSONDecodeError:
        raise ErrorChatGPT("GPT devolvió un plan que no se pudo leer. Probá de nuevo.")
    faltan = [k for k in esquema.get("required", []) if k not in data]
    if faltan:
        raise ErrorChatGPT(f"GPT devolvió un plan incompleto (falta {', '.join(faltan)}). Probá de nuevo.")
    return data


def _stream(pedido):
    partes, completo = [], False
    try:
        with _cliente().responses.create(**pedido) as stream:
            for ev in stream:
                if ev.type == "response.output_text.delta":
                    partes.append(ev.delta)
                elif ev.type == "response.failed":
                    err = ev.response.error
                    codigo = err.code if err else "error"
                    raise ErrorChatGPT(ERRORES.get(codigo, f"GPT no pudo responder ({codigo})."))
                elif ev.type == "response.incomplete":
                    raise ErrorChatGPT("La respuesta de GPT quedó incompleta. Probá de nuevo.")
                elif ev.type == "response.completed":
                    completo = True
    except openai.AuthenticationError:
        raise ErrorChatGPT("Tu sesión de ChatGPT venció. Volvé a conectarte en Configuración.")
    except openai.PermissionDeniedError as e:
        raise ErrorChatGPT(ERRORES.get(_codigo(e), "Tu cuenta de ChatGPT no tiene acceso a este modelo."))
    except openai.RateLimitError as e:
        raise ErrorChatGPT(ERRORES.get(_codigo(e), "ChatGPT está saturado. Probá en un minuto."))
    except openai.APIConnectionError:
        raise ErrorChatGPT("No hay conexión con ChatGPT.")
    if not completo:
        raise ErrorChatGPT("GPT cortó la respuesta antes de terminar. Probá de nuevo.")
    return "".join(partes)
