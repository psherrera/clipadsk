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

---

## Actualizaciones

Desde la app: **Config → Actualizar Aplicación** ejecuta `git pull` automáticamente.

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
│   ├── main.py            ← API FastAPI
│   ├── requirements.txt
│   ├── Dockerfile
│   └── downloads/         ← archivos descargados (auto-creado)
├── frontend/
│   ├── index.html
│   ├── main.js
│   └── style.css
├── docker-compose.yml
├── iniciar.bat            ← arranque diario en Windows
├── install.ps1            ← instalación inicial en Windows
├── yt-dlp.exe             ← motor de descarga (auto-descargado)
└── .env.template          ← plantilla de variables de entorno
```

---

## Requisitos

| Herramienta | Mínimo | Notas |
|---|---|---|
| Python | 3.10+ | Auto-instalable con `install.ps1` |
| FFmpeg | cualquiera | Necesario para audio; auto-instalable |
| yt-dlp | última versión | Auto-descargado al iniciar |
| Git | cualquiera | Para actualizaciones automáticas |
| GROQ_API_KEY | — | Opcional; acelera la transcripción |
