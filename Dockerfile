# pyvelm production image — multi-stage build.
#
# Stage 1 compiles the Tailwind + Flowbite assets that ship inside the
# Python package. Stage 2 carries only the runtime: the compiled CSS,
# the Python source, the project deps, gunicorn + uvicorn-worker.
#
# Build:
#     docker build -t pyvelm:latest .
# Run (alongside the docker-compose.yml in this directory):
#     docker compose up

# ────────────────────────────── Stage 1: build CSS ──
FROM node:20-alpine AS css

WORKDIR /src

# Install just what the build needs — package*.json change rarely.
COPY package.json package-lock.json* ./
RUN npm install --silent

# The tailwind config + source CSS live next to the templates so the
# CSS build can scan them for utility-class usage.
COPY pyvelm/static ./pyvelm/static
COPY pyvelm/templates ./pyvelm/templates
RUN npm run build


# ────────────────────────────── Stage 2: runtime ──
FROM python:3.13-slim AS runtime

# Don't write .pyc; flush stdout/stderr immediately so docker logs work.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Minimal OS deps: psycopg ships its own libpq via the [binary] extra,
# so we only need libstdc++ at runtime. The slim base already has it.

# Run as a non-root user so a container compromise doesn't get root
# inside the namespace.
RUN groupadd --system pyvelm && \
    useradd --system --gid pyvelm --home-dir /app --shell /sbin/nologin pyvelm

WORKDIR /app

# Install Python deps first so the layer cache survives source edits.
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install . gunicorn uvicorn[standard]

# Copy the source + the CSS artifact built in stage 1. The dist
# directory is what main.html links to via /web/static/dist/pyvelm.css.
COPY pyvelm ./pyvelm
COPY examples ./examples
COPY --from=css /src/pyvelm/static/dist ./pyvelm/static/dist
COPY --from=css /src/pyvelm/static/dist/flowbite.min.js ./pyvelm/static/dist/flowbite.min.js

# gunicorn config lives next to the Dockerfile so it's discoverable.
COPY gunicorn_conf.py ./

USER pyvelm

EXPOSE 8000

# Sanity: PYVELM_DSN must be set in the runtime environment (compose
# passes it through from .env). The container exits early with a clear
# error if it's missing.
CMD ["gunicorn", "-c", "gunicorn_conf.py", "examples.serve:app"]
