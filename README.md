# Editor de video

App local y open source que convierte un video tuyo hablando a cámara en un reel listo para subir.
Claude elige el gancho, corta lo que no suma y cierra con el llamado a la acción; la app saca
los silencios, lleva el video a vertical, quema subtítulos con la palabra resaltada y normaliza el audio.

- **Reel**: vertical 9:16, de 30 a 60 s, una sola idea.
- **Pantalla doble**: arriba un gráfico o imagen, abajo vos hablando.
- **Recortes de YouTube**: de un video largo, Claude propone de 3 a 5 reels y vos elegís cuáles armar.

Todo corre en tu compu. La transcripción es local y gratis (Parakeet v3 de NVIDIA). Solo se manda
a Claude el **texto** de la transcripción, nunca el video.

## Cómo funciona

1. **Subís el video** y elegís el formato.
2. **Se transcribe** con tiempos por palabra.
3. **Claude arma el plan**: orden de los cortes, textos en pantalla y b-roll sugerido.
4. **Revisás y ajustás**: tiempos, orden, textos, colores de subtítulos, ritmo y encuadre. También
   podés pedirle cambios a Claude en lenguaje natural ("el gancho tiene que ser la parte de los 3 clientes").
5. **Borrador**: un render rápido en baja resolución para revisar.
6. **Final**: `.mp4` de 1080×1920 y `.srt` con los subtítulos.

## Requisitos

- macOS o Linux con Python 3.10 o más nuevo.
- **ffmpeg con libass** (para quemar los subtítulos). En Mac el `ffmpeg` de Homebrew ya no trae
  libass; instalá la variante completa, que queda aparte y la app la encuentra sola:
  ```bash
  brew install ffmpeg-full
  ```
  En Linux: `sudo apt install ffmpeg` (ya trae libass).
- Una **cuenta de Anthropic Console** para usar Claude (se cobra por uso de API).

## Instalación

```bash
git clone <este-repo> editor-de-video
cd editor-de-video
./iniciar.sh
```

La primera vez crea el entorno e instala las dependencias. Después abre http://localhost:8000.
La primera transcripción descarga el modelo (~490 MB) a `~/.cache/editor-de-video`.

## Conectar tu cuenta de Anthropic

En la app: **⚙ Configuración → Iniciar sesión con Anthropic**. Usa la herramienta oficial `ant`:

```bash
brew install anthropics/tap/ant
```

Al iniciar sesión se abre el navegador, elegís la organización y el workspace, y listo: la app
usa esa sesión sin que tengas que copiar ninguna clave. También podés pegar una clave de API
si preferís.

> **¿Y mi suscripción de claude.ai (Pro / Max)?** Anthropic no permite que apps de terceros
> ofrezcan el login de claude.ai, así que esta app se conecta con una cuenta de
> [Anthropic Console](https://console.anthropic.com) (facturación por uso de API).

El modelo que usa es Claude Opus 5.5. Armar el plan de un video de 10 minutos suele costar menos de un dólar.

## O usar GPT con tu plan de ChatGPT

Si tenés ChatGPT Plus o Pro, podés usar GPT para decidir los cortes sin pagar API aparte:
**⚙ Configuración → GPT → Continue with ChatGPT**. Se abre una pestaña de OpenAI: iniciás sesión,
aceptás usar tu plan en esta app y listo. El uso cuenta dentro de los límites de tu plan, y podés
elegir el modelo entre los que tenga tu cuenta.

Usa [Sign in with ChatGPT](https://developers.openai.com/siwc) para apps open source. Los tokens se
guardan solo en tu compu, en `~/.config/editor-de-video/`. Con el plan de ChatGPT no se pueden
generar imágenes, así que para el b-roll sigue haciendo falta una clave de API.

## B-roll con IA (opcional)

Claude sugiere imágenes de apoyo para los momentos concretos del video. Para generarlas, cargá en
Configuración una clave de **OpenAI** (GPT Image) o **Gemini** (Nano Banana). La app te dice cuántas
imágenes va a generar antes de hacerlo, porque cada una tiene costo. También podés usar tus propias
imágenes o no usar b-roll.

## Estructura

```
app/
  main.py          API (FastAPI): proyectos, trabajos en segundo plano, login
  ia.py            Decisiones editoriales (reglas, esquemas y llamada a Claude)
  chatgpt.py       Sign in with ChatGPT y llamadas a GPT con el plan del usuario
  editor/          Los scripts que hacen el trabajo pesado
    transcribir.py   Transcripción con tiempos por palabra
    editar.py        Corte, encuadre, subtítulos y audio a partir de un plan.json
    generar_broll.py Imágenes de b-roll con GPT Image o Nano Banana
    SKILL.md         Las reglas editoriales originales
  static/          Interfaz (HTML + JS sin build)
proyectos/         Tus proyectos (no se sube a git)
```

Cada proyecto guarda una copia del video; **tu archivo original nunca se modifica**. Los scripts de
`app/editor/` también funcionan solos desde la terminal (ver `app/editor/SKILL.md`).

## Licencia

MIT. Ver [LICENSE](LICENSE).
