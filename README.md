# Clipadsk 🎬

Descargador y transcriptor de video 100% local.  
Soporta YouTube, Instagram y más. Sin login, sin nube, sin telemetría.

---

## Instalación en Windows 10 / 11

No hace falta saber programar ni tener permisos de administrador. Se instala Python
(si no está), FFmpeg, las dependencias y un acceso directo **Clipadsk** en el Escritorio.

### Opción 1 — Una línea (recomendada)

1. Abrí el menú Inicio, escribí **PowerShell** y abrilo.
2. Pegá esta línea y apretá Enter:

```powershell
irm https://raw.githubusercontent.com/psherrera/clipadsk/main/instalar.ps1 | iex
```

3. Esperá unos minutos. Al terminar, Clipadsk se abre solo en el navegador.

Se instala en `%LOCALAPPDATA%\Clipadsk`.

### Opción 2 — Descargando el ZIP

1. En esta página: botón verde **Code → Download ZIP**.
2. Descomprimí el ZIP donde quieras (por ejemplo en Documentos).
3. Doble clic en **`INSTALAR.bat`**.
   Si Windows muestra "Windows protegió su PC": **Más información → Ejecutar de todas formas**.

### Si ya tenés una versión anterior de Clipadsk

Pegá **la misma línea** de la Opción 1 en PowerShell. El instalador busca la instalación
anterior (por ejemplo `C:\clipadsk` o una carpeta en Documentos), pregunta si actualizarla
ahí mismo y la actualiza conservando `.env`, cookies, FFmpeg y el historial.

- Si Clipadsk está abierto, el instalador lo cierra y lo vuelve a abrir al final.
- Si la versión vieja tenía archivos modificados (por ejemplo `yt-dlp.exe` actualizado
  desde la app), se guardan con `git stash` en vez de borrarse.
- Si elegís "instalación nueva", se instala en `%LOCALAPPDATA%\Clipadsk`, se copian `.env`
  y cookies, y la carpeta vieja se puede borrar. El historial se mantiene igual, porque se
  guarda en el navegador.

No uses el botón "Actualizar aplicación" de la versión vieja: puede fallar si actualizaste
el motor alguna vez. Desde esta versión en adelante, ese botón ya funciona siempre.

### Primer uso

La primera vez la app pide una **API Key de Groq** (gratis, sin tarjeta) para transcribir
rápido con IA: [console.groq.com/keys](https://console.groq.com/keys).

### Uso diario

Doble clic en el ícono **Clipadsk** del Escritorio (o en `iniciar.bat`).

### Actualizar

Desde la app: **Configuración → Actualizar aplicación**. También se puede volver a correr
el instalador: actualiza sin borrar la configuración, las cookies ni el historial.

### Si algo falla

El instalador guarda un registro en `%TEMP%\clipadsk-instalacion.log` y el servidor en
`backend\clipadsk.log`. Mandá esos archivos a quien te pasó Clipadsk.

### Mensaje para pasarle a alguien

> Para instalar Clipadsk: abrí **PowerShell** desde el menú Inicio, pegá esta línea y apretá Enter:
>
> `irm https://raw.githubusercontent.com/psherrera/clipadsk/main/instalar.ps1 | iex`
>
> Tarda unos minutos y después se abre sola. Para usarla otro día, buscá el ícono **Clipadsk** en el Escritorio.
> La primera vez te pide una clave gratis de Groq: creala en https://console.groq.com/keys

---

## Arranque con Docker

```bash
cp .env.template .env
# Editar .env y agregar GROQ_API_KEY si se desea

docker-compose up -d --build
```

- App: http://localhost:5000

Para detener: `docker-compose down`

---

## Configuración (opcional pero recomendada)

### GROQ API Key — transcripción rápida con IA

1. Creá una cuenta gratis en [console.groq.com](https://console.groq.com/keys)
2. Copiá tu clave
3. Pegala en la app: **Config → API Key de Groq**  
   (se guarda en tu navegador, no en el servidor)

### Cookies — para videos con restricción de edad

Exportá cookies desde el navegador con la extensión
[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
y guardá el archivo como `cookies.txt` en la carpeta raíz del proyecto.

---

## Transcripción

El sistema usa tres métodos en cascada:

1. **Subtítulos directos** — si el video tiene subtítulos en español o inglés, los extrae sin descargar audio (más rápido, sin IA).
2. **Groq Whisper v3** — si `GROQ_API_KEY` está configurado, transcribe en la nube de Groq (rápido, gratuito).
3. **Whisper local** — si instalás `faster-whisper`, el backend puede transcribir sin Groq usando un modelo local.

Los audios largos se dividen automáticamente en partes de 20 minutos. La limpieza con IA solo corrige puntuación y párrafos: **no resume ni cambia lo dicho**, para que las citas sean textuales.

Las herramientas de IA (resumen, citas, datos, ángulos, diarización y chat) analizan la transcripción **completa**, aunque sea larga: la dividen en partes y combinan los resultados.

Para verificar una cita palabra por palabra, el botón **Original** muestra el texto tal como salió de la transcripción, antes de la corrección con IA. Si la IA cambió palabras de lo dicho, Clipadsk descarta su versión de ese tramo y avisa.

---

## Novedades de la versión 3.1

- **Carruseles de Instagram:** al pegar un carrusel aparecen todas las fotos y videos. Clic para elegir, doble clic para verla grande. Se baja una sola, las elegidas (en .zip) o todo el carrusel.
- **Clipa.exe:** doble clic en `CREAR_EXE.bat` para generarlo (tarda unos minutos). Si la carpeta tiene la instalación (`backend\venv`), el exe la usa y corre siempre la versión actual; si no, funciona solo, con los datos en `clipadsk_datos`. Hay que volver a generarlo solo si se usa sin instalación y salió una versión nueva.
- **Clipa para Claude (MCP):** doble clic en `INSTALAR_MCP.bat` y reiniciar Claude Desktop. Claude puede pedirle a Clipa que transcriba un enlace o un archivo, busque en el historial, traduzca, resuma o saque citas; Clipa hace el trabajo en la PC y a Claude le llega solo el texto. Si Clipadsk está cerrado, se abre solo. La key de Groq tiene que estar en `.env` (`GROQ_API_KEY=`), porque la que se carga en el navegador no le llega.

## Novedades de la versión 3

- **Pegar y listo:** un solo ítem "Pegar enlace" para todas las plataformas; al pegar un enlace se analiza solo.
- **Trabajos en segundo plano:** las transcripciones corren en el servidor aunque cierres la pestaña. Desde el botón de trabajos (arriba a la derecha) podés pegar varios enlaces juntos; la app avisa con una notificación cuando cada uno termina.
- **Historial en la PC:** se guarda en la base de datos de Clipadsk (`backend/clipadsk.db`), no en el navegador. La búsqueda encuentra también lo que se dijo, con o sin tildes. El historial viejo del navegador se pasa solo la primera vez.
- **Visualizador ("Ver y cortar"):** reproduce el video con el texto sincronizado (resalta la frase y la palabra que se está diciendo). Clic en una frase o palabra para saltar; seleccioná un tramo de texto o arrastrá sobre la línea de tiempo para marcar el recorte. Con YouTube usa el reproductor de YouTube; con otras plataformas baja una copia liviana; los archivos propios se reproducen directo desde la PC.
- **Recortes para redes:** descarga del tramo con subtítulos quemados y/o en vertical 9:16.
- **Vista bilingüe:** traducción frase por frase al lado del original, alineada con los tiempos.
- **Citas listas para pegar:** se copian con atribución, minuto y enlace al segundo exacto.
- **Errores que dicen qué hacer** (cookies vencidas, video privado, límite de Groq, sin conexión...) y aviso al abrir la app si las cookies de YouTube vencieron.
- **Detalles:** tiempos por palabra, forma de onda, estimación del tiempo de transcripción, búsqueda dentro de la transcripción, guardado automático al editar, arrastrar archivos a cualquier parte de la ventana, diálogos propios y atajos de teclado (tecla `?` para verlos).

---

## Estructura

```
clipadsk/
├── backend/
│   ├── main.py            ← API FastAPI (endpoints)
│   ├── config.py          ← variables de entorno, rutas y logging
│   ├── text_utils.py      ← subtítulos, SRT, citas, URLs (funciones puras)
│   ├── media.py           ← FFmpeg + transcripción (Groq / Whisper local)
│   ├── ai.py              ← limpieza, traducción y herramientas periodísticas
│   ├── history.py         ← historial de transcripciones (SQLite)
│   ├── errors.py          ← mensajes de error claros (causa + qué hacer)
│   ├── requirements.txt
│   ├── requirements-pinned.txt  ← versiones exactas probadas
│   ├── downloads/         ← archivos temporales (auto-creado)
│   └── media_cache/       ← copias livianas para el visualizador (se borran solas)
├── frontend/              ← index.html, main.js, v3.js (funciones de la versión 3), style.css, v3.css
├── tests/                 ← tests (pytest)
├── docker-compose.yml
├── instalar.ps1           ← instalador / actualizador (Windows)
├── INSTALAR.bat           ← doble clic para instalar desde el ZIP
├── iniciar.bat            ← arranque diario en Windows
└── .env.template          ← plantilla de configuración
```

---

## Seguridad

- Por defecto el servidor **solo acepta conexiones desde esta PC** (`127.0.0.1`).
  Para usarlo desde otras PCs de la red, poné `HOST=0.0.0.0` en `.env` y definí `ADMIN_TOKEN`.
- Solo la propia app (o los orígenes de `FRONTEND_ALLOWED_ORIGINS`) puede llamar a la API:
  otras páginas web abiertas en el navegador no pueden usarla.
- La API key de Groq cargada desde la app queda guardada solo en tu navegador.
- Si usás Clipadsk desde otras PCs de la red, todas comparten el mismo historial (está en el servidor).

---

## Desarrollo

```bash
pip install -r requirements-dev.txt
ruff check .
pytest -q
```

Para regenerar `backend/requirements-pinned.txt`: `scripts/pin_requirements.ps1` (Windows) o `scripts/pin_requirements.sh`.

**Frontend sin internet:** Tailwind, JSZip y las fuentes están en `frontend/vendor/` (no se cargan de ningún CDN). Si agregás o cambiás clases de Tailwind en `index.html`, `setup.html` o `main.js`, regenerá el CSS con `powershell -ExecutionPolicy Bypass -File scripts\build_css.ps1` (necesita Node.js solo para esto; la app no lo necesita) y subí también `frontend/vendor/`. Al cambiar `style.css`, `main.js` o el CSS compilado, subí el número de versión (`?v=`) en `index.html` y en `sw.js` para que el navegador recargue.

---

## Requisitos

| Herramienta | Mínimo | Notas |
|---|---|---|
| Python | 3.10+ | Lo instala `instalar.ps1` si falta |
| FFmpeg | cualquiera | Lo descarga `instalar.ps1` dentro de la carpeta de la app |
| yt-dlp | última versión | Se instala con las dependencias; se actualiza desde Configuración |
| Git | — | Opcional: sin git, las actualizaciones se bajan como ZIP de GitHub |
| API Key de Groq | — | Gratis; transcripción rápida y herramientas de IA |
