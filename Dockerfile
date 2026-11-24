# Image backend Pathora. Dipakai Railway, Fly.io, Cloud Run, atau hosting lain berbasis Docker.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY . .

# Database disimpan di volume persisten yang dipasang di /data (atur di hosting).
ENV DATABASE_PATH=/data/pathora.db
EXPOSE 8000

# --proxy-headers: alamat IP asli pengguna dibaca dari header proxy hosting (untuk batas laju per IP).
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
