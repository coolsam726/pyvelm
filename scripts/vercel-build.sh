#!/usr/bin/env bash
# Vercel build: compile assets, install pyvelm from this repo, reset demo DB.
set -euo pipefail

npm ci
npm run build
pip install '.[geo]'

export PYVELM_ENV=production
export PYVELM_ALLOW_DB_NUKE=1

# Preview builds have no live traffic on the new URL. Production deploys run
# while the previous deployment is still serving — its serverless instances
# hold Postgres locks and can block DROP SCHEMA until they go idle.
if [[ "${VERCEL_ENV:-}" == "production" ]]; then
  echo "Production deploy: waiting for idle DB connections before nuke…"
  sleep "${PYVELM_NUKE_DELAY_SECONDS:-45}"
  export PYVELM_NUKE_ATTEMPTS="${PYVELM_NUKE_ATTEMPTS:-20}"
  export PYVELM_NUKE_LOCK_TIMEOUT="${PYVELM_NUKE_LOCK_TIMEOUT:-180s}"
fi

pyvelm db nuke -y
