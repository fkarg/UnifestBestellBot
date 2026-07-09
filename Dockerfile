FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim

LABEL org.opencontainers.image.source="https://github.com/fkarg/UnifestBestellBot"
LABEL org.opencontainers.image.description="Telegram ordering bot and live dashboard for Karlsruhe Unifest"
LABEL org.opencontainers.image.licenses="GPL-3.0-or-later"

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_DEV=1
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /app/logs \
    && chown -R app:app /app

USER app
EXPOSE 8000

CMD ["unifestbestellbot"]
