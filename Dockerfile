FROM node:20-alpine AS ui-build

WORKDIR /app/atlas-ui
COPY atlas-ui/package*.json ./
RUN npm ci
COPY atlas-ui/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY scripts/ scripts/
COPY main.py ./
COPY --from=ui-build /app/atlas-ui/build atlas-ui/build

EXPOSE 8000

CMD ["sh", "-c", "gunicorn --bind :${PORT:-8000} --workers 1 --threads 8 --timeout 900 main:app"]
