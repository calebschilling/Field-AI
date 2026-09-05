# One image, three processes.
#
# api / worker / enhancer share this image. Compose starts them as
# separate containers so a crash in one does not take down the others.
#
# We do not copy .env into the image. Compose injects it at runtime.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py audio.py db.py studio.py llm.py main.py worker.py enhance.py send_wav_file.py schema.sql inbox.html ./

# Production path. Compose bind-mounts ./data/audio on the host here
# so wavs survive rebuilds and `docker compose down`.
RUN mkdir -p /audio
ENV AUDIO_DIR=/audio \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Default is the HTTP server. worker.py overrides this in compose.
CMD ["python", "main.py"]
