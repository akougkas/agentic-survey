# Traefik labels for citadl.gnosis.run

`citadl/deploy/coolify/docker-compose.yml` publishes two routers on the
Coolify-managed Traefik instance. The labels live on the `backend`
(FastAPI) and `frontend` (SvelteKit) services; Coolify injects them into
the Traefik provider when the stack comes up.

## Pattern: HTTP-only entrypoint, no TLS on Traefik

Blade's existing `gnosis-run-site` uses the same pattern, confirmed from
`~/dotfiles/homelab/inventory.yaml`:

```yaml
traefik:
  node: blade
  port: 80
  proto: http
  notes: "Reverse proxy. Routes by Host header to site containers."
```

Traefik listens on `web` (port 80). TLS is terminated at Cloudflare's edge;
the cloudflared tunnel delivers plain HTTP to Traefik. Internal traffic
(Traefik → container) is also plain HTTP.

This is why the compose labels use `entrypoints=web` and omit both
`tls=true` and any cert resolver. A prior draft used
`entrypoints=websecure` with `tls=true`, which would fail against this
blade topology because no TLS listener is configured on Traefik.

## Labels on `backend`

```yaml
labels:
  - traefik.enable=true
  - traefik.http.routers.citadl-surveys-api.rule=Host(`citadl.gnosis.run`) && PathPrefix(`/api`)
  - traefik.http.routers.citadl-surveys-api.entrypoints=web
  - traefik.http.routers.citadl-surveys-api.priority=100
  - traefik.http.services.citadl-surveys-api.loadbalancer.server.port=8100
```

- `rule` matches API calls. `PathPrefix(/api)` scopes the router to
  backend routes only.
- `priority=100` — higher than the frontend router's `10` so `/api/*`
  beats the catch-all frontend rule.
- `server.port=8100` points Traefik at FastAPI's uvicorn port; the
  container uses `expose: "8100"`, not `ports:`, so the port is reachable
  only to Traefik, not to the blade host.

## Labels on `frontend`

```yaml
labels:
  - traefik.enable=true
  - traefik.http.routers.citadl-surveys.rule=Host(`citadl.gnosis.run`)
  - traefik.http.routers.citadl-surveys.entrypoints=web
  - traefik.http.routers.citadl-surveys.priority=10
  - traefik.http.services.citadl-surveys.loadbalancer.server.port=3000
```

- `rule` is the Host-only catch-all; everything not matched by the API
  router lands on SvelteKit.
- `priority=10` — loses to the API router's `100` for `/api/*`.
- `server.port=3000` is SvelteKit's adapter-node listener.

## SSE / streaming

SvelteKit proxies `/api/*` to the backend (see
`apps/web/src/routes/api/[...path]/+server.ts`). Traefik does not
buffer; SSE streams should flow end-to-end provided the Cloudflare edge
has caching disabled for the hostname. In the Cloudflare dashboard,
`citadl.gnosis.run` should have:

- Caching Level: **Bypass** (or a page rule that sets `Cache-Control: no-store`
  for `/api/**/events`).
- Rocket Loader: **Off** (it rewrites inline scripts the SSE client needs).

These are Cloudflare-dashboard settings, not Traefik labels, but they are
part of the deploy checklist.

## Local verification (no blade involvement)

Bring the stack up on a laptop where Traefik is not present:

```bash
cd citadl/deploy/coolify
docker compose up backend frontend surrealdb searxng
# Traefik is absent, so the labels are inert; the containers still run.
curl http://localhost:3000/     # frontend direct
curl http://localhost:8100/api/healthz   # backend direct
```

To test the Traefik routing locally, spin up a minimal Traefik with
`--entryPoints.web.address=:80` and `--providers.docker` on the same
network; the labels above will be picked up automatically.
