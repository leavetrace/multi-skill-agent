# Minimal image for the skillagent CLI (optional; the brief calls Docker "a plus").
# The API key is passed at run time with `--env-file .env`; `.env` is never copied in
# (see .dockerignore).
#   docker build -t skillagent .
#   docker run --rm -it --env-file .env skillagent                # interactive session
#   docker run --rm --env-file .env skillagent ask "What is 15% of 2,480?"
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.10 /uv /uvx /bin/

ENV PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so editing the source does not invalidate this layer.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY skillagent ./skillagent
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 agent
USER agent

# --no-sync: the image already holds the runtime dependencies; never add dev tools at run time.
ENTRYPOINT ["uv", "run", "--no-sync", "python", "-m", "skillagent"]
