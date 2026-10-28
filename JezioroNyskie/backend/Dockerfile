# Backend Mielizna. Kontekst budowania: katalog JezioroNyskie/ (backend zależy od ../pipeline).
FROM python:3.12-slim
# rasterio (koła z wbudowanym GDAL) wymaga libexpat w obrazie slim
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PATH="/app/backend/.venv/bin:$PATH"
WORKDIR /app
# pipeline (pakiet `mielizna`, zależność lokalna) + metadane backendu najpierw: warstwa zależności się cache'uje
COPY pipeline/ /app/pipeline/
COPY backend/pyproject.toml backend/uv.lock /app/backend/
WORKDIR /app/backend
RUN uv sync --locked --no-dev --no-install-project
COPY backend/app /app/backend/app
ENV MIELIZNA_DATA_DIR=/data MIELIZNA_CURRENT_DIR=/cache/current
# użytkownik bez uprawnień; /cache należy do niego (nowy wolumen dziedziczy właściciela z obrazu)
RUN useradd --system --uid 10001 mielizna && mkdir -p /cache/current && chown -R mielizna /cache
USER mielizna
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=5s --start-period=10s --retries=30 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/meta', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
