# Financial News Portfolio Advisor — container image.
# Works on any host that runs a Docker image and sets $PORT (Render, Railway,
# Fly.io, Google Cloud Run, etc.).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hosts inject the port to listen on via $PORT; default to 8000 locally.
ENV PORT=8000
EXPOSE 8000

# Bind to 0.0.0.0 so the host can route to it. Shell form so ${PORT} expands.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
