"""Decisiones editoriales con Claude (o GPT vía ChatGPT): elegir candidatos y armar el plan de cortes.

Claude trabaja con tiempos del video ORIGINAL (es lo único que ve en la transcripción).
Los textos, gráficos y b-roll se convierten después a tiempos del video final con
la misma lógica de silencios que usa editar.py.
"""
import json

import anthropic

MODELO = "claude-opus-5-5"

REGLAS = """Sos un editor de video para redes. Recibís la transcripción de un video (frases con
tiempos en segundos del video original) y decidís qué queda y en qué orden.

Reglas de corte:
1. Una idea por pieza. Si hay dos ideas, quedate con la más fuerte.
2. El gancho va primero: la frase más fuerte (un dolor, una contradicción, un resultado
   concreto) es el primer corte, aunque en el original esté en el medio.
3. Afuera lo que no suma: saludos, "bueno", "como les decía", repeticiones, frases que
   arrancan y se abandonan, tomas repetidas (si dice algo dos veces, quedate con la mejor,
   normalmente la última).
4. El cierre es el llamado a la acción. Uno solo.
5. Respetá sus palabras. No reordenes frases sueltas para fabricar algo que no dijo. Se
   mueven bloques enteros con sentido completo.
6. Los tiempos salen de la transcripción: cortá en el inicio de la primera frase y el final
   de la última. Nunca inventes tiempos. Los cortes no se superponen entre sí.
7. Los silencios dentro de cada corte se sacan solos; no hace falta marcarlos.

Textos en pantalla: uno o dos como mucho, de máximo 6 palabras. El primero refuerza el
gancho y aparece al inicio. Se expresan con tiempos del ORIGINAL que caigan dentro de un corte.

B-roll: solo donde se dice algo concreto que se puede mostrar. Entre 0 y 4, de 2 a 3
segundos cada uno, nunca en el gancho ni en el llamado a la acción. El prompt en inglés,
describiendo la escena, sin texto en la imagen. Tiempos del ORIGINAL dentro de un corte.

Gráficos (solo pantalla doble): asigná las imágenes disponibles a los tramos donde se
habla de lo que muestran. Tiempos del ORIGINAL dentro de un corte. Si no hay imágenes, vacío.

No inventás datos ni cambiás lo que dijo. No opinás sobre el mensaje, la oferta o el nicho;
si el contenido tiene un problema de fondo, decilo en una línea en "advertencia"."""

_TRAMO = {"type": "object", "additionalProperties": False,
          "required": ["desde", "hasta"],
          "properties": {"desde": {"type": "number"}, "hasta": {"type": "number"}}}

ESQUEMA_PLAN = {
    "type": "object",
    "additionalProperties": False,
    "required": ["cortes", "textos", "broll", "graficos", "llamado_a_la_accion", "resumen", "advertencia"],
    "properties": {
        "cortes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["desde", "hasta", "nota", "que_dice"],
            "properties": {"desde": {"type": "number"}, "hasta": {"type": "number"},
                           "nota": {"type": "string", "description": "gancho, desarrollo, llamado a la acción..."},
                           "que_dice": {"type": "string", "description": "resumen de una línea"}}}},
        "textos": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["desde", "hasta", "texto", "posicion"],
            "properties": {**_TRAMO["properties"], "texto": {"type": "string"},
                           "posicion": {"type": "string", "enum": ["arriba", "centro"]}}}},
        "broll": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["desde", "hasta", "prompt"],
            "properties": {**_TRAMO["properties"], "prompt": {"type": "string"}}}},
        "graficos": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["desde", "hasta", "imagen"],
            "properties": {**_TRAMO["properties"], "imagen": {"type": "string"}}}},
        "llamado_a_la_accion": {"type": "string"},
        "resumen": {"type": "string", "description": "por qué este orden, en 1-2 líneas"},
        "advertencia": {"type": "string", "description": "vacío si no hay nada que advertir"},
    },
}

ESQUEMA_CANDIDATOS = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidatos"],
    "properties": {"candidatos": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["titulo", "desde", "hasta", "idea", "gancho"],
        "properties": {"titulo": {"type": "string"}, "desde": {"type": "number"},
                       "hasta": {"type": "number"}, "idea": {"type": "string"},
                       "gancho": {"type": "string"}}}}},
}


class ErrorIA(Exception):
    pass


def _pedir_claude(sistema, usuario, esquema):
    client = anthropic.Anthropic()
    try:
        with client.beta.messages.stream(
            model=MODELO,
            max_tokens=64000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": esquema}},
            system=sistema,
            messages=[{"role": "user", "content": usuario}],
        ) as stream:
            msg = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise ErrorIA("Tu sesión de Anthropic venció o la clave no es válida. Volvé a conectarte en Configuración.")
    except anthropic.RateLimitError:
        raise ErrorIA("Claude está saturado (límite de uso). Probá en un minuto.")
    except anthropic.APIConnectionError:
        raise ErrorIA("No hay conexión con la API de Anthropic.")
    except anthropic.APIStatusError as e:
        raise ErrorIA(f"La API de Anthropic respondió {e.status_code}: {e.message}")
    if msg.stop_reason == "refusal":
        raise ErrorIA("Claude no pudo procesar este contenido.")
    if msg.stop_reason == "max_tokens":
        raise ErrorIA("La respuesta de Claude quedó cortada. Probá de nuevo.")
    texto = "".join(b.text for b in msg.content if b.type == "text")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        raise ErrorIA("Claude devolvió un plan que no se pudo leer. Probá de nuevo.")


def _pedir(motor, sistema, usuario, esquema):
    """motor: {"motor": "claude"} o {"motor": "gpt", "modelo": "<slug>"}."""
    if (motor or {}).get("motor") == "gpt":
        from . import chatgpt
        if not motor.get("modelo"):
            raise ErrorIA("Elegí un modelo de GPT en Configuración.")
        return chatgpt.pedir_json(motor["modelo"], sistema, usuario, esquema)
    return _pedir_claude(sistema, usuario, esquema)


def _frases_txt(frases, desde=None, hasta=None):
    out = []
    for f in frases:
        if desde is not None and f["e"] < desde:
            continue
        if hasta is not None and f["s"] > hasta:
            continue
        out.append(f"[{f['s']:.2f} - {f['e']:.2f}] {f['texto']}")
    return "\n".join(out)


FORMATOS = {
    "reel": "Reel vertical 9:16, entre 30 y 60 segundos, una sola idea.",
    "doble": "Pantalla doble: arriba un gráfico o imagen, abajo la persona hablando. Entre 30 y 60 segundos.",
}


def generar_plan(transcripcion, formato, cta, notas, imagenes, rango=None, plan_previo=None, indicaciones="",
                 motor=None):
    desde, hasta = rango if rango else (None, None)
    partes = [
        f"Formato: {FORMATOS.get(formato, FORMATOS['reel'])}",
        f"Duración del original: {transcripcion['duracion']:.1f} s",
        "Llamado a la acción pedido: " + (cta or "(no lo dijo; usá el que diga el propio video)"),
    ]
    if rango:
        partes.append(f"Este reel sale SOLO del fragmento {desde:.2f}-{hasta:.2f} s del original.")
    if formato == "doble":
        partes.append("Imágenes disponibles: " + (", ".join(imagenes) if imagenes else "ninguna"))
    if notas:
        partes.append(f"Notas del usuario: {notas}")
    if plan_previo:
        partes.append("Plan anterior (tiempos del original):\n" + json.dumps(plan_previo, ensure_ascii=False))
    if indicaciones:
        partes.append(f"Cambios que pide el usuario sobre el plan anterior: {indicaciones}")
    partes.append("Transcripción:\n" + _frases_txt(transcripcion["frases"], desde, hasta))
    return _pedir(motor, REGLAS, "\n\n".join(partes), ESQUEMA_PLAN)


def generar_candidatos(transcripcion, cta, notas, motor=None):
    usuario = "\n\n".join([
        "Este es un video largo. Proponé entre 3 y 5 fragmentos que funcionen como reels "
        "independientes de 30 a 60 segundos, cada uno con una sola idea y un gancho propio. "
        "Los tiempos marcan el tramo del original de donde sale cada uno (puede durar más que el "
        "reel final, se recorta después). Los tramos no se superponen.",
        "Llamado a la acción: " + (cta or "(el que diga el propio video)"),
        f"Notas del usuario: {notas}" if notas else "",
        "Transcripción:\n" + _frases_txt(transcripcion["frases"]),
    ])
    return _pedir(motor, REGLAS, usuario, ESQUEMA_CANDIDATOS)["candidatos"]
