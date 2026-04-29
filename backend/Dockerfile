FROM python:3.11-slim

# Dependencias del sistema: solo FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar PyTorch CPU primero (capa pesada separada para mejor cache)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Instalar el resto de dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --upgrade yt-dlp

# Código de la app
COPY main.py .

# Directorios de trabajo
ENV WHISPER_CACHE_DIR=/app/model
RUN mkdir -p /app/model /app/downloads

EXPOSE 5000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-5000}"]

