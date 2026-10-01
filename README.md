# Clipadsk 🎬

Descargador y transcriptor de video 100% local.  
Soporta YouTube, Instagram y más. Sin login, sin nube, sin telemetría.

---

## Arranque rápido (Windows)

### Primera vez (instalación)

Hacé doble clic en `install.ps1` o ejecutalo en PowerShell:

```powershell
.\install.ps1
```

Instala Python, FFmpeg y yt-dlp si no están, crea el entorno virtual e instala las dependencias.

### Uso diario

```bat
iniciar.bat
```

Levanta el backend y abre la app en el navegador automáticamente.

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

---

## Actualizaciones

Desde la app: **Config → Actualizar Aplicación** ejecuta `git pull` e instala las dependencias nuevas. Después hay que cerrar y volver a abrir `iniciar.bat`.

**Config → Actualizar motor** actualiza yt-dlp (útil cuando YouTube o Instagram dejan de funcionar).

O manualmente:

```bat
git pull origin main
iniciar.bat
```

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
│   ├── requirements.txt
│   ├── requirements-pinned.txt  ← versiones exactas probadas
│   └── downloads/         ← archivos temporales (auto-creado)
├── frontend/              ← index.html, main.js, style.css
├── tests/                 ← tests (pytest)
├── docker-compose.yml
├── iniciar.bat            ← arranque diario en Windows
├── install.ps1            ← instalación inicial en Windows
└── .env.template          ← plantilla de configuración
```

---

## Seguridad

- Por defecto el servidor **solo acepta conexiones desde esta PC** (`127.0.0.1`).
  Para usarlo desde otras PCs de la red, poné `HOST=0.0.0.0` en `.env` y definí `ADMIN_TOKEN`.
- Solo la propia app (o los orígenes de `FRONTEND_ALLOWED_ORIGINS`) puede llamar a la API:
  otras páginas web abiertas en el navegador no pueden usarla.
- La API key de Groq cargada desde la app queda guardada solo en tu navegador.

---

## Desarrollo

```bash
pip install -r requirements-dev.txt
ruff check .
pytest -q
```

Para regenerar `backend/requirements-pinned.txt`: `scripts/pin_requirements.ps1` (Windows) o `scripts/pin_requirements.sh`.

---

## Requisitos

| Herramienta | Mínimo | Notas |
|---|---|---|
| Python | 3.10+ | Auto-instalable con `install.ps1` |
| FFmpeg | cualquiera | Necesario para audio; auto-instalable |
| yt-dlp | última versión | Auto-descargado al iniciar |
| Git | cualquiera | Para actualizaciones automáticas |
| GROQ_API_KEY | — | Opcional; acelera la transcripción |
