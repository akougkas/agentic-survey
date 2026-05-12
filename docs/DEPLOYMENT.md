# Deployment

Two flavors. Local dev uses SurrealDB in Docker and `make` targets. Blade
production uses Coolify, Traefik, and an existing cloudflared tunnel.

---

## Local dev

```bash
# 1. SurrealDB up
docker compose -f infra/docker-compose.local.yml up -d surrealdb

# 2. Apply the schema (idempotent; every DEFINE is IF NOT EXISTS)
cd services/api && uv run python -m agentic_survey.db.schema

# 3. Boot the backend (demo bundle + in-memory repo)
make api-dev

# or: boot against the CITADEL bundle (still in-memory by default)
make api-dev-citadl

# 4. Boot the frontend
make web-dev

# 5. End-to-end smoke
SURVEY_ADMIN_PASSWORD=change-me infra/ops/smoke.sh
```

Reset local Surreal state:

```bash
docker compose -f infra/docker-compose.local.yml down -v
docker compose -f infra/docker-compose.local.yml up -d surrealdb
cd services/api && uv run python -m agentic_survey.db.schema
```

LiteLLM live smoke against the configured mini endpoint:

```bash
cd services/api
SURVEY_LLM_ENABLED=true uv run python -m agentic_survey.llm.router --smoke mira-chatter
```

---

## Blade production (`citadl.gnosis.run`)

Blade already runs:

- Coolify (PaaS control plane, port 8000, Tailscale-only)
- Traefik (reverse proxy, port 80, HTTP-only)
- cloudflared (systemd, `blade-tunnel` id `246390fe`, routes `gnosis.run` →
  Traefik at `localhost:80`)
- `gnosis-run-site` (static site, pattern reference for CITADEL's labels)

### Boot order

Compose handles it via `depends_on` in
`citadl/deploy/coolify/docker-compose.yml`:

1. `surrealdb` comes up first.
2. `searxng` in parallel.
3. `backend` waits for both. Apply the canonical schema separately via
   `python -m agentic_survey.db.schema` (idempotent; every `DEFINE` has
   `IF NOT EXISTS`). Typically run once per Coolify deploy.
4. `worker` (freshness heartbeat; no real work in v1) and `frontend`
   follow `backend`.

### Environment variables

All `SURVEY_*` vars are documented in `.env.example`. The minimum set
Coolify must inject:

| Variable | Value | Notes |
|---|---|---|
| `SURVEY_API_IMAGE` | *(set pushed API image)* | Used by backend and worker. |
| `SURVEY_WEB_IMAGE` | *(set pushed web image)* | Used by SvelteKit frontend. |
| `SURVEY_PUBLIC_BASE_URL` | `https://citadl.gnosis.run` | Used for invite URLs. |
| `SURVEY_FRONTEND_ORIGIN` | `https://citadl.gnosis.run` | CORS. |
| `SURVEY_PRODUCT_BUNDLE_DIR` | `/app/citadl/bundle` | Mounted read-only from the repo. |
| `SURVEY_ADMIN_PASSWORD` | *(set a real one)* | Cookie-auth secret. |
| `SURVEY_LLM_ENABLED` | `true` | Flip off only for non-LLM route checks. |
| `SURVEY_CHATTER_ENDPOINT_URL` | `http://192.168.86.141:8080/v1` | URL serving Brain A (Mira's voice). |
| `SURVEY_CHATTER_MODEL` | `Nemotron-3-Nano-Omni-30B-A3B-Reasoning-UD-Q4_K_M` | Model alias `mira-chatter` resolves to on mini. |
| `SURVEY_CHATTER_TEMPERATURE` | `0.7` | Per-call temperature for Brain A (warm conversational). |
| `SURVEY_SCIENTIST_ENDPOINT_URL` | `http://192.168.86.143:1234/v1` | URL serving Brain B + Validator + Analyst + Ingest on dynamo. |
| `SURVEY_SCIENTIST_MODEL` | `nvidia-nemotron-3-nano-omni-30b-a3b-reasoning` | Model alias `mira-scientist` and friends resolve to on dynamo. |
| `SURVEY_SCIENTIST_TEMPERATURE` | `0.3` | Per-call temperature for Brain B (focused tool selection). |
| `SURVEY_SCIENTIST_SUPPORTS_REASONING` | `true` | Nemotron OMNI supports the scientist-family thinking mode. |
| `SURVEY_SCIENTIST_CONTEXT_WINDOW_TOKENS` | `600000` | Informational context-window setting used by the catalog. |
| `SURVEY_EMBEDDING_MODEL` | `text-embedding-nomic-embed-text-v2-moe` | Embeddings alias `embeddings` on dynamo. |
| `SURVEY_DEFAULT_INTERVIEWER_ENDPOINT` | `chatter` | Session pin for Brain A foreground chatter. |
| `SURVEY_LLM_TIMEOUT_SECONDS` | `60` | Per-call ceiling. |
| `SURVEY_LLM_PREPLAN_REASONING_BUDGET_TOKENS` | `1024` | Cold-start Brain B pre-plan hidden reasoning budget. |
| `SURVEY_REPOSITORY` | `surreal` | Do not run memory repo in production. |
| `SURVEY_SURREAL_URL` | `ws://surrealdb:8000/rpc` | Compose resolves the `surrealdb` service name. |
| `SURVEY_SURREAL_NS` | `agentic` | Bundle-specific namespace. |
| `SURVEY_SURREAL_DB` | `citadl` | Bundle-specific database. |
| `SURVEY_SURREAL_USER` / `SURVEY_SURREAL_PASS` | `root` / `root` | Change post-demo. |
| `SURVEY_SEARXNG_URL` | `http://searxng:8080` | Internal compose name. |

The compose file supplies sensible defaults for everything except the
image tags, `SURVEY_ADMIN_PASSWORD`, and the two LLM endpoint URLs.

### LLM endpoints (LAN, blade is on the same subnet)

- **mini** serves Brain A through `Nemotron-3-Nano-Omni-30B-A3B-Reasoning-UD-Q4_K_M`: `http://192.168.86.141:8080/v1`
- **dynamo** serves Brain B through `nvidia-nemotron-3-nano-omni-30b-a3b-reasoning`: `http://192.168.86.143:1234/v1`

Both hosts are reachable from blade on the `192.168.86.0/24` LAN.
Tailscale equivalents work too if the LAN is ever partitioned; swap the
IP for the Tailscale address in Coolify without rebuilding.

### Cloudflared route

See `infra/cloudflared/README.md`. Summary: add `citadl.gnosis.run →
http://localhost:80` as a public hostname on the existing `blade-tunnel`
via Cloudflare Zero Trust. No tunnel restart needed; cloudflared on blade
refreshes on the fly.

### Traefik labels

See `infra/traefik/labels.md`. The compose uses `entrypoints=web` and omits
`tls=*` because Cloudflare terminates edge TLS and Traefik operates HTTP-only
on port 80. This matches the existing `gnosis-run-site` pattern confirmed in
`~/dotfiles/homelab/inventory.yaml`.

### Deploy (operator-run)

1. Confirm the runtime verifies clean locally:
   `make verify` (runs bundle-validate, api-test, web-check, web-build).
2. Build and push the current API and web images to the registry blade can
   pull from.
3. In Coolify (`http://100.124.181.9:8000`), create a new **Docker Compose**
   application pointed at this repo with compose file path
   `citadl/deploy/coolify/docker-compose.yml`.
4. Fill in the env vars from the table above; mark
   `SURVEY_ADMIN_PASSWORD` as secret.
5. Add the public hostname in Cloudflare Zero Trust per
   `infra/cloudflared/README.md`.
6. Click **Deploy** in Coolify.
7. Smoke: `infra/ops/smoke.sh https://citadl.gnosis.run/api`.

### Verify

```bash
curl -sS https://citadl.gnosis.run/api/healthz
# {"status":"ok"}

curl -sS https://citadl.gnosis.run/api/system/context | jq '.bundle_slug, .campaign_seed_count'
# "citadl"
# 3
```

Open `https://citadl.gnosis.run/` in a browser — you should see the
CITADEL operator console shell.

### Rollback

Coolify's **Redeploy previous image** button reverts to the last green
build. Surreal data lives on the `surreal_data` named volume and is
preserved across redeploys. To wipe: remove the volume and re-run the
migration.

---

## Images

Production images build from:

- `docker/Dockerfile.api` → `python:3.12-slim` + `uv sync`, runs
  `uvicorn agentic_survey.main:app` on port 8100.
- `docker/Dockerfile.web` → `node:22-alpine` build, adapter-node output,
  runs `node build` on port 3000.

Both are built automatically by the Coolify compose stack. To build
locally for verification:

```bash
cd /home/akougkas/projects/agentic-survey
docker build -f docker/Dockerfile.api -t agentic-survey-api:latest .
docker build -f docker/Dockerfile.web -t agentic-survey-web:latest .

# Quick import check on the API image:
docker run --rm agentic-survey-api:latest \
    python -c "from agentic_survey.main import create_app; create_app()"
```

---

## Operational notes

- SurrealDB data lives in the `surreal_data` named volume. Bind-mounts
  aren't used on blade so Coolify volume snapshots cover backups.
- The bundle is mounted read-only at `/app/citadl/bundle`; container
  writes to it will fail loudly, which is intentional — bundles are
  authored in git, not edited live.
- Generated campaign export ZIPs land in `SURVEY_EXPORT_DIR`
  (default `./campaigns`). Mount a host path or a Coolify volume there
  if you want them to survive redeploys.
- The `worker` service runs `agentic_survey.tools.freshness`, which is
  currently a heartbeat only. It is left in the compose so the full M4
  freshness loop can land without a stack redeploy.
