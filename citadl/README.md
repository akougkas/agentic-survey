# Citadl

Citadl is the mounted product layer that currently lives inside the `agentic-survey` repo. The runtime stays generic; Citadl owns its bundle data, branding, and blade/Coolify deployment shape.

## Layout

- `bundle/` - product manifest, branding, and campaign seeds
- `deploy/coolify/` - product-specific deployment config for blade
- `docs/` - product notes and product-specific design material
- `Makefile` - local commands that run Citadl against the sibling runtime in this repo

## Local Run

Backend with the Citadl bundle mounted:

```bash
make -C citadl api-dev
```

Frontend against that backend:

```bash
make -C citadl web-dev
```

Bundle validation:

```bash
make -C citadl bundle-validate
```

## Deployment

`deploy/coolify/docker-compose.yml` builds the runtime from the current repo and mounts `citadl/bundle` into the backend and worker containers. That keeps blade deployment simple now. When Citadl moves out to its own repo later, the same bundle directory can stay intact and the compose file can switch from local build contexts to pinned runtime images.
