FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Instalar ffmpeg y dependencias del sistema
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg \
       build-essential \
       libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar sólo requirements primero para aprovechar cache de docker
COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

# Copiar el resto de la aplicación
COPY . /app

EXPOSE 5000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]
