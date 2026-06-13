FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Berlin

WORKDIR /app

# Dependency layer (cached unless lockfile changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application
COPY README.md ./
COPY src/ src/
COPY config/ config/
COPY migrations/ migrations/
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Oneshot runs: docker compose run --rm app python -m arestoteles.runs.<name>
CMD ["python", "-m", "arestoteles.runs.main_run", "--help"]
