# The image the quotes timer runs scripts/refresh_quotes.py in (deploy/systemd/arestoteles-quotes.service).
# It keeps the old tag `arestoteles-app:latest` so the timer unit stays as it is. The script is mounted at run
# time, so the image holds only Python and alpaca-py. Build (no context needed):
#   docker build -t arestoteles-app:latest - < deploy/quotes.Dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/Berlin

RUN pip install --no-cache-dir alpaca-py==0.43.4

WORKDIR /app
CMD ["python", "/app/refresh_quotes.py"]
