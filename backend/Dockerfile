# One image, two roles: the API serves requests, the worker runs indexing
# jobs. They share every dependency and the embedding model, so building
# them separately would only mean downloading the model twice.
FROM python:3.12-slim AS base

# git is not a convenience here: ingest clones repositories and reads
# their history for the git_log tool.
RUN apt-get update \
    && apt-get install --no-install-recommends -y git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first: they change far less often than the code, so this
# layer survives most rebuilds.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# Bake the embedding model into the image. Left to first boot it is a
# download on every deploy, and on a cold container that download sits
# in front of the first user.
ENV FASTEMBED_CACHE_PATH=/app/.model-cache
RUN uv run python -c "\
from config import get_settings; from fastembed import TextEmbedding; \
TextEmbedding(get_settings().embedding_model); \
print('embedding model cached')"

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Overridden per role in compose; the API is the sensible default.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
