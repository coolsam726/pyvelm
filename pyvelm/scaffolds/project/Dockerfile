# Production image for a pyvelm app.
#
# pyvelm itself ships the compiled CSS / Flowbite assets inside its
# wheel, so we don't need a node build step — just install Python
# deps, copy the app code, and run gunicorn.

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system app && \
    useradd --system --gid app --home-dir /app --shell /sbin/nologin app

WORKDIR /app

# Install Python deps first so the layer cache survives source edits.
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install . gunicorn uvicorn[standard]

COPY app ./app
COPY gunicorn_conf.py ./

USER app
EXPOSE 8000

CMD ["gunicorn", "-c", "gunicorn_conf.py", "app.serve:app"]
