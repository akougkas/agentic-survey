#!/usr/bin/env sh
# Backend container entrypoint.
#
# Applies the canonical SurrealDB schema before exec'ing the container
# command (uvicorn, freshness worker, ad-hoc python, etc.). The schema
# applier is idempotent because every DEFINE in schema.surql is guarded
# by IF NOT EXISTS, so running on every container start is safe even
# when the SurrealDB volume is reused across redeploys.
#
# Coolify reuses the surreal_data volume between releases. Without this
# shim, a deploy that adds new tables or fields to schema.surql leaves
# the production DB on the old layout because docker-entrypoint-initdb.d
# only fires on first container boot. The shim fixes that.
#
# Skipped when SURVEY_REPOSITORY != surreal so memory-mode runs (tests,
# local dev that opted into in-memory repo) do not require a database.

set -e

repository="${SURVEY_REPOSITORY:-memory}"
if [ "$repository" = "surreal" ]; then
    deadline=$(( $(date +%s) + 30 ))
    attempt=1
    while :; do
        if python -m agentic_survey.db.schema; then
            break
        fi
        now=$(date +%s)
        if [ "$now" -ge "$deadline" ]; then
            echo "entrypoint: schema apply failed after 30s of retries" >&2
            exit 1
        fi
        echo "entrypoint: schema apply attempt $attempt failed; retrying in 2s" >&2
        attempt=$((attempt + 1))
        sleep 2
    done
fi

exec "$@"
