# Deployment

Local SurrealDB:

```bash
docker compose -f infra/docker-compose.local.yml up -d surrealdb
```

Apply the M1 schema:

```bash
cd services/api
uv run python -m agentic_survey.db.migrations.runner
```

The runner now applies [schema.surql](/home/akougkas/projects/agentic-survey/services/api/agentic_survey/db/schema.surql) directly. There is no migration tracking table; to reset local state, drop the SurrealDB volume and re-apply the schema:

```bash
docker compose -f infra/docker-compose.local.yml down -v
docker compose -f infra/docker-compose.local.yml up -d surrealdb
cd services/api
uv run python -m agentic_survey.db.migrations.runner
```

Run the LiteLLM smoke path against the configured mini endpoint:

```bash
cd services/api
SURVEY_LLM_ENABLED=true uv run python -m agentic_survey.llm.router --smoke mira-chatter
```

Run the API against the demo bundle and the in-memory repository:

```bash
make api-dev
```

Run the Citadl seed bundle instead:

```bash
make api-dev-citadl
```

The local export directory is `./campaigns`, and the checked-in LiteLLM seed config lives at [services/api/agentic_survey/llm/litellm_config.yaml](/home/akougkas/projects/agentic-survey/services/api/agentic_survey/llm/litellm_config.yaml).
