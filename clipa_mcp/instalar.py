"""
Registra Clipa en Claude Desktop (agrega "clipa" a claude_desktop_config.json sin tocar lo demás).
Lo ejecuta INSTALAR_MCP.bat con el Python de backend/venv.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "clipa_mcp" / "server.py"


def config_paths() -> list:
    """Dónde guarda Claude Desktop su configuración (instalador normal y versión de la Microsoft Store)."""
    paths = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for pkg in (Path(local) / "Packages").glob("Claude_*"):
            paths.append(pkg / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json")
    if sys.platform == "darwin":
        paths.append(Path.home() / "Library/Application Support/Claude/claude_desktop_config.json")
    elif os.name != "nt":
        paths.append(Path.home() / ".config/Claude/claude_desktop_config.json")
    existing = [p for p in paths if p.parent.exists()]
    return existing or paths[:1]


def python_for_mcp() -> str:
    """python.exe (no pythonw): Claude Desktop habla con el servidor por la entrada/salida estándar."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        exe = exe.parent / "python.exe"
    return str(exe)


def install(path: Path, groq_key: str = "") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {}
    if path.exists():
        text = path.read_text(encoding="utf-8-sig").strip()
        if text:
            config = json.loads(text)
        shutil.copy2(path, path.with_suffix(f".json.respaldo-{time.strftime('%Y%m%d-%H%M%S')}"))
    env = {"CLIPA_URL": os.environ.get("CLIPA_URL", "http://127.0.0.1:5000"), "CLIPA_DIR": str(ROOT)}
    if groq_key:
        env["CLIPA_GROQ_KEY"] = groq_key
    config.setdefault("mcpServers", {})["clipa"] = {"command": python_for_mcp(), "args": [str(SERVER)], "env": env}
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def ensure_groq_key():
    """Las transcripciones que pide Claude usan la key del .env de Clipadsk (la del navegador no le llega)."""
    env_file = ROOT / ".env"
    text = env_file.read_text(encoding="utf-8-sig") if env_file.exists() else ""
    if any(line.strip().startswith("GROQ_API_KEY=") and line.split("=", 1)[1].strip() for line in text.splitlines()):
        return
    try:
        key = input("  Pega tu key de Groq (empieza con gsk_) y Enter, o solo Enter para saltear: ").strip()
    except EOFError:
        key = ""
    if key:
        with env_file.open("a", encoding="utf-8") as f:
            f.write(("" if not text or text.endswith("\n") else "\n") + f"GROQ_API_KEY={key}\n")
        print("  Key guardada en .env (reinicia Clipadsk para que la tome).")
    else:
        print("  Sin key de Groq en .env: para transcribir desde Claude vas a tener que cargarla despues.")


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else ""
    if not key:
        ensure_groq_key()
    for p in config_paths():
        print(f"  Configurado: {install(p, key)}")
