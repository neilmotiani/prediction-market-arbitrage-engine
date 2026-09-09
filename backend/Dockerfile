FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
COPY backend ./backend
RUN uv sync --frozen --no-dev
COPY docs/contract-mappings.json ./docs/contract-mappings.json
RUN useradd --create-home researcher && chown -R researcher:researcher /app
USER researcher
ENV PYTHONPATH=/app/backend
EXPOSE 8000
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
