---
name: editor-de-video
description: Edita videos de punta a punta para redes. Transcribe, elige el gancho, corta y reordena, saca silencios, lleva a vertical o pantalla doble, quema subtítulos con la palabra resaltada, agrega textos y entrega el .mp4 listo. Usar cuando el usuario pida editar, recortar o convertir un video en reel o pantalla doble, o sacar recortes de un video de YouTube.
---

# Editor de video

Editás el video vos. El usuario te da un archivo y recibe un `.mp4` listo para subir. Tu trabajo es decidir qué queda y en qué orden; los scripts hacen el corte, el encuadre, los subtítulos y el audio.

Los scripts están en la carpeta `scripts/` de esta skill:
- `transcribir.py`: transcripción con tiempos por palabra con Parakeet v3 de NVIDIA (corre local y gratis, entiende español e inglés sin configurar nada).
- `editar.py`: arma el video a partir de un `plan.json`.

## 0. Antes de empezar (solo la primera vez)

Revisá que estén instalados `ffmpeg` y `sherpa-onnx`:

```bash
ffmpeg -version && python3 -c "import sherpa_onnx, numpy"
```

Si falta algo, instalalo vos con el comando que corresponda y avisale al usuario en una línea:
- ffmpeg: `brew install ffmpeg` (Mac) · `winget install ffmpeg` (Windows) · `sudo apt install ffmpeg` (Linux)
- sherpa-onnx: `pip install sherpa-onnx numpy`

La primera transcripción descarga el modelo (~490 MB desde GitHub) y lo deja en `~/.cache/editor-de-video`. Avisale al usuario que esa vez tarda un par de minutos más.

Trabajá siempre en una carpeta nueva al lado del video (`<nombre-del-video>-edicion/`). Nunca modifiques ni borres el video original.

## 1. Lo que necesitás saber

1. **El video.**
2. **El formato.** Si no lo dice, preguntá con estas opciones:
   - **Reel**: vertical 9:16, entre 30 y 60 segundos, una sola idea.
   - **Pantalla doble**: arriba un gráfico, captura o imagen y abajo el usuario hablando. Pedile las imágenes (PNG o JPG). Si no tiene, hacelo igual sin gráficos y avisale.
   - **Recortes de YouTube**: de un video largo, entre 3 y 5 reels independientes.
3. **El llamado a la acción** (comentar una palabra, ir al link, seguir la cuenta). Si no lo dice, usá el que diga el propio video. Si no dice ninguno, preguntá en una línea.

## 2. Transcribir

```bash
python3 scripts/transcribir.py VIDEO --salida CARPETA
```

El idioma se detecta solo. Si la descarga del modelo falla, probá con `--motor whisper` (requiere `pip install faster-whisper`). Leé `CARPETA/transcripcion.txt` entero antes de decidir nada. Ahí están las frases con sus tiempos.

## 3. Decidir los cortes

1. **Una idea por pieza.** Si hay dos ideas, son dos reels.
2. **El gancho va primero.** Elegí la frase más fuerte (un dolor, una contradicción, un resultado concreto) y ponela como primer corte, aunque en el original esté en el medio.
3. **Afuera lo que no suma**: saludos, "bueno", "como les decía", repeticiones, frases que arrancan y se abandonan, tomas repetidas (si dice algo dos veces, quedate con la mejor, normalmente la última).
4. **El cierre es el llamado a la acción.** Uno solo.
5. **Respetá sus palabras.** No reordenes frases sueltas para fabricar algo que no dijo. Se mueven bloques enteros con sentido completo.
6. **Los tiempos salen de la transcripción.** Cortá en el inicio de la primera palabra y el final de la última, nunca a mitad de palabra. No inventes tiempos.

Los silencios dentro de cada corte se sacan solos (jump cuts), no hace falta que los marques.

## 4. Escribir el plan

Creá `CARPETA/plan.json`. Los `cortes` van en el orden final y con tiempos del video original. `textos` y `graficos` usan tiempos del video final (empieza en 0).

```json
{
  "formato": "reel",
  "cortes": [
    {"desde": 84.2, "hasta": 91.6, "nota": "gancho"},
    {"desde": 12.0, "hasta": 38.4, "nota": "desarrollo"},
    {"desde": 102.3, "hasta": 108.9, "nota": "llamado a la acción"}
  ],
  "recortar_silencios": 0.45,
  "textos": [
    {"desde": 0, "hasta": 3, "texto": "Máximo 6 palabras", "posicion": "arriba"}
  ],
  "graficos": [
    {"desde": 0, "hasta": 8, "imagen": "grafico1.png"}
  ],
  "subtitulos": {
    "activar": true,
    "color": "#FFFFFF",
    "resaltado": "#FFD400",
    "palabras_por_linea": 3,
    "mayusculas": false
  },
  "encuadre_x": 0.5,
  "encuadre_y": 0.5
}
```

- `formato`: `"reel"` o `"doble"`. `graficos` solo se usa en `"doble"`. Las rutas de las imágenes son relativas a la carpeta del plan.
- `recortar_silencios`: pausas más largas que esto (en segundos) se cortan. `0.45` es dinámico; subilo a `0.7` si el usuario quiere un ritmo más tranquilo, `null` para no tocar las pausas.
- `textos`: uno o dos por pieza como mucho, cortos. El primero refuerza el gancho. `posicion`: `"arriba"` o `"centro"`.
- `encuadre_x`: dónde está la persona en un video horizontal (0 = izquierda, 0.5 = centro, 1 = derecha). Si el video ya es vertical, dejalo en 0.5.
- `encuadre_y`: lo mismo en vertical (0 = arriba, 0.5 = centro, 1 = abajo). Importa cuando sobra video arriba y abajo, por ejemplo un video vertical en pantalla doble: subilo hacia 0.2–0.3 si la cara queda cortada. Si dudás, sacá un fotograma con `ffmpeg -ss 5 -i VIDEO -frames:v 1 frame.png` y miralo.
- Si el usuario tiene colores de marca, usalos en `resaltado`.

### B-roll

Agregalo solo donde el video dice algo concreto que se puede mostrar (un panel en cero, una agenda llena, mensajes entrando). Entre 2 y 4 por reel, de 2 a 3 segundos cada uno, nunca en el gancho ni en el llamado a la acción, donde tiene que verse la cara.

```json
"broll": [
  {"desde": 12.4, "hasta": 14.9, "prompt": "close-up of a laptop showing an ads dashboard with every result at zero, dim home office at night"}
]
```

- Los tiempos son del video final. Para sacarlos, mirá en qué segundo del final cae la frase (los cortes del plan se suman en orden y los silencios se descuentan; el `.srt` del borrador te da los tiempos exactos).
- Si el usuario te da su propia imagen o clip, usá `"imagen": "archivo.png"` o `"video": "clip.mp4"` en lugar de `prompt`.
- Si hay `prompt`, generá las imágenes con la clave de API del usuario (`OPENAI_API_KEY` para GPT Image o `GEMINI_API_KEY` para Nano Banana). Antes de generar, decile cuántas imágenes vas a crear: cada una cuesta.
  ```bash
  python3 scripts/generar_broll.py CARPETA/plan.json --calidad medium
  ```
  El script guarda `broll-1.png`, `broll-2.png`... y completa el plan solo.
- Los prompts en inglés, describiendo la escena, sin texto en la imagen. Las imágenes entran a pantalla completa con un zoom lento y los subtítulos quedan encima.

## 5. Borrador, revisión y final

1. Renderizá el borrador (rápido, baja resolución):
   ```bash
   python3 scripts/editar.py VIDEO CARPETA/transcripcion.json CARPETA/plan.json CARPETA/borrador.mp4 --borrador
   ```
2. Revisalo vos antes de mostrarlo: sacá 3 fotogramas (inicio, medio, final) con `ffmpeg -ss T -i borrador.mp4 -frames:v 1 fT.png`, miralos y corregí el encuadre o los textos si algo tapa la cara o se sale de cuadro. Leé el `.srt` que se generó al lado: el primer subtítulo tiene que ser el gancho.
3. Mostrale al usuario una tabla corta (orden, de dónde sale cada corte, qué dice) y la duración final, y pasale el borrador.
4. Con su OK (o sus cambios aplicados al plan), renderizá el final sin `--borrador`:
   ```bash
   python3 scripts/editar.py VIDEO CARPETA/transcripcion.json CARPETA/plan.json CARPETA/final.mp4
   ```
5. Entregá `final.mp4` (1080x1920, listo para subir) y `final.srt` por si quiere subir los subtítulos aparte.

## 6. Recortes de YouTube

Primero listá entre 3 y 5 fragmentos candidatos: tiempos, la idea en una línea y el gancho de cada uno. Preguntá cuáles quiere. Después hacé un `plan-N.json` y un `final-N.mp4` por cada recorte elegido, con el paso 5 completo para cada uno.

## 7. Lo que no hacés

- No inventás tiempos, frases ni datos, y no cambiás lo que dijo el usuario.
- No agregás música ni efectos de sonido. No generás imágenes sin avisar antes cuántas son, porque se pagan con la clave del usuario.
- No opinás sobre el mensaje, la oferta o el nicho. Si el contenido tiene un problema de fondo, decilo en una línea y sugerí revisarlo con su mentora.
- No borrás ni pisás el video original.
