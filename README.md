# Clipadsk 🎬

Descargador y transcriptor de video 100% local.  
Soporta YouTube e Instagram. Sin login, sin nube, sin telemetría.

## CI and pinned dependencies

This repository includes a GitHub Actions workflow at `.github/workflows/ci.yml` that runs linting, tests and `pip-audit`, and generates a pinned `backend/requirements-pinned.txt` as an artifact.

To produce a pinned `requirements` file locally (recommended before committing), run one of the scripts:

On Unix/macOS:

```bash
./scripts/pin_requirements.sh
```

On Windows PowerShell:

```powershell
.\scripts\pin_requirements.ps1
```

After running the script, commit `backend/requirements-pinned.txt` if you want the pinned versions in the repo.


---

## Requisitos

| Herramienta | Mínimo | Notas |
|---|---|---|
| Python | 3.10+ | |
| FFmpeg | cualquiera | necesario para audio/transcripción |
| GROQ_API_KEY | — | opcional; acelera la transcripción via Groq |
| faster-whisper | opcional | instalar para transcribir localmente con el modelo `small` |

---

## Arranque rápido (Windows)

```bat
iniciar.bat
```

El script crea un `venv`, instala dependencias la primera vez,
levanta el backend y abre el frontend automáticamente.

---

## Arranque manual

```bash
# 1. Entorno e instalación
cd backend
python -m venv venv
venv/Scripts/activate          # Windows
# source venv/bin/activate     # Linux / macOS

pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# 2. Variables de entorno (opcional)
cp ../.env.example ../.env
# editar .env y agregar GROQ_API_KEY si se desea

# 3. Iniciar backend
python main.py
```

Luego abrir `frontend/index.html` en el navegador.

---

## Arranque con Docker

```bash
# Copiar y editar variables de entorno
cp .env.example .env

docker-compose up -d --build
```

- Frontend: http://localhost  
- Backend:  http://localhost:5000

Para detener: `docker-compose down`

---

## Transcripción

El sistema usa tres métodos en cascada:

1. **Subtítulos directos** – si YouTube tiene subtítulos en español o inglés, los extrae sin descargar audio (más rápido, sin IA).
2. **Groq Whisper v3** – si `GROQ_API_KEY` está configurado y el audio es < 25 MB, lo transcribe en la nube de Groq (rápido).
3. **Whisper local (opcional)** – si instalas `faster-whisper`, el backend puede transcribir archivos locales sin Groq usando un modelo local (`small` por defecto).
4. **Whisper local con Groq inválido** – si tu llave Groq no funciona, la app ahora intentará usar `faster-whisper` si está disponible.

---

## Cookies (para videos con restricción de edad o login)

Exportar cookies desde el navegador con la extensión
[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
y guardar el archivo como `cookies.txt` en la carpeta raíz del proyecto.  
El backend lo detecta automáticamente.

---

## Estructura

```
clipadsk/
├── backend/
│   ├── main.py            ← API FastAPI (solo local)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── downloads/         ← videos descargados (auto-creado)
├── frontend/
│   ├── index.html
│   ├── main.js            ← siempre apunta a 127.0.0.1:5000
│   ├── style.css
│   └── sw.js
├── docker-compose.yml
├── iniciar.bat            ← arranque Windows sin Docker
└── .env.example
```
