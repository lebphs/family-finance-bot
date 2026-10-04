FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/src/ ./src/
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
RUN npm run build

FROM python:3.11.0-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production STATE_DIR=/app/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home appuser \
    && mkdir /app/data && chown appuser /app/data
COPY backend/ ./backend/
COPY handlers/ ./handlers/
COPY keyboards/ ./keyboards/
COPY main.py config.py scheduler_bot.py sheet.py ./
COPY --from=frontend /build/dist ./frontend/dist
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import os, urllib.request; port=os.getenv('PORT') or os.getenv('API_PORT', '8000'); urllib.request.urlopen('http://127.0.0.1:' + port + '/health', timeout=3)"
CMD ["python", "main.py"]
