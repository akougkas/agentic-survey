# cloudflared — citadl.gnosis.run route

The blade homelab already runs a Cloudflare tunnel (`blade-tunnel`, id
`246390fe`) that routes `gnosis.run` and `akougkasworkbench.us` to the
Traefik reverse proxy on `blade:80`. To publish `citadl.gnosis.run` we add
one more public hostname to the same tunnel; no new tunnel, no new cert,
no systemd change.

## TLS model

```
Internet ──HTTPS──▶ Cloudflare edge ──HTTP (tunnel)──▶ blade:80 (Traefik)
                                                      └─▶ citadl-frontend:3000
                                                      └─▶ citadl-surveys-api:8100
```

Cloudflare terminates TLS at its edge. The tunnel carries plain HTTP to
Traefik; Traefik forwards plain HTTP to the container ports. No cert
management inside the tunnel or the compose stack.

## Add the hostname

### Option A — Cloudflare Zero Trust dashboard (recommended)

1. Cloudflare Zero Trust → **Networks → Tunnels**.
2. Select `blade-tunnel` (id `246390fe`).
3. **Public Hostnames → Add a public hostname**.
4. Fields:
   - Subdomain: `citadl`
   - Domain: `gnosis.run`
   - Type: `HTTP`
   - URL: `localhost:80`
5. **Additional application settings → TLS** — leave defaults (no origin TLS;
   `HTTP Host Header` empty).
6. Save.

Propagation is near-instant; `dig citadl.gnosis.run` should return Cloudflare
edge IPs within seconds.

### Option B — CLI (run on blade, operator-executed)

```bash
# Requires cloudflared logged in and blade-tunnel locally configured.
cloudflared tunnel route dns blade-tunnel citadl.gnosis.run
```

`cloudflared` on blade is a systemd service; no restart is needed after the
route add — the service refreshes hostnames on the fly.

## Verify

```bash
# From anywhere on the internet:
curl -I https://citadl.gnosis.run/api/healthz

# Expected:
# HTTP/2 200
# content-type: application/json
```

If you get `404` from Traefik, the Host rule in
`citadl/deploy/coolify/docker-compose.yml` is not loaded yet (deploy the
compose stack via Coolify first). If you get `530`/`1033` from Cloudflare,
the tunnel hostname has not propagated or the tunnel is down on blade
(`sudo systemctl status cloudflared` on blade).

## Do not

- Create a new Cloudflare tunnel. The existing `blade-tunnel` is the
  single ingress for all `*.gnosis.run` services.
- Enable origin TLS in the public hostname settings. Traefik receives
  plain HTTP; origin TLS would fail handshake.
- Touch the systemd unit or the tunnel token on blade.
