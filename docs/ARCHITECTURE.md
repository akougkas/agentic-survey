# Architecture

Agentic Survey is a reusable runtime for designing, running, and reviewing structured interview campaigns.

## Repo Boundary

- `services/api/agentic_survey` is the runtime core: campaign state machine, interview loop, agent logic, repository contracts, and API surface.
- `apps/web` is the generic operator and participant shell.
- `examples/product-bundles/demo` is the default runnable bundle for local development and open-source distribution.
- `citadl/` is an in-repo product folder for now: bundle data, product docs, and blade/Coolify deployment config.

The runtime owns behavior every mounted product needs. A product bundle owns the parts the runtime should never silently invent: branding, host identity, campaign seeds, consent copy, and product-specific deployment choices.

## Core Components

- **Frontend:** SvelteKit + TypeScript, split between participant chat and operator admin flows.
- **Backend:** FastAPI app exposing REST and SSE endpoints.
- **Database:** SurrealDB for document, vector, and graph storage.
- **Search:** SearXNG for design-time and freshness ingestion.
- **Worker:** background freshness loop and future analysis/report jobs.

## Bundle Contract

- The runtime resolves an active bundle directory from `SURVEY_PRODUCT_BUNDLE_DIR`.
- If that env var is unset, the runtime falls back to `examples/product-bundles/demo`.
- Bundles declare product metadata in `product.yaml` and campaign seeds in `campaigns/*.yaml`.
- Seed-backed campaigns can be materialized directly into runtime state without copying product content into runtime code.

## Runtime Defaults

- Mira is the default interviewer persona.
- Admin auth is an env-var password.
- Freshness cadence defaults to `03:00` server local time and can be overridden per campaign.
- The same API and web shell can run against any bundle that satisfies the contract.
