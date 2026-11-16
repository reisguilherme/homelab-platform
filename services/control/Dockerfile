FROM python:3.12-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/control ./services/control
COPY services/telemetry ./services/telemetry
ENV PATH="/app/.venv/bin:$PATH"
USER 10001:10001
CMD ["uvicorn", "services.control.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
