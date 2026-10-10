FROM node:22-alpine AS frontend
WORKDIR /build
COPY mini_app/frontend/package.json mini_app/frontend/package-lock.json ./
RUN npm ci
COPY mini_app/frontend/src/ ./src/
COPY mini_app/frontend/index.html mini_app/frontend/tsconfig.json mini_app/frontend/vite.config.ts ./
RUN npm run build

FROM python:3.11.0-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production STATE_DIR=/app/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home appuser \
    && mkdir /app/data && chown appuser /app/data
COPY bot/ ./bot/
COPY mini_app/backend/ ./mini_app/backend/
COPY mini_app/__init__.py mini_app/__main__.py ./mini_app/
COPY config.py ./
COPY --from=frontend /build/dist ./mini_app/frontend/dist
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import os, urllib.request; port=os.getenv('PORT') or os.getenv('API_PORT', '8000'); urllib.request.urlopen('http://127.0.0.1:' + port + '/health', timeout=3)"
CMD ["python", "-m", "mini_app"]
