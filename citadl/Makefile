BUNDLE_DIR := $(abspath ./bundle)

.PHONY: api-dev web-dev bundle-validate deploy-config

api-dev:
	cd ../services/api && SURVEY_PRODUCT_BUNDLE_DIR=$(BUNDLE_DIR) uv run uvicorn agentic_survey.main:app --reload --host 127.0.0.1 --port 8100

web-dev:
	cd ../apps/web && SURVEY_API_PROXY_TARGET=http://127.0.0.1:8100 npm run dev -- --host 127.0.0.1 --port 5270

bundle-validate:
	cd ../services/api && SURVEY_PRODUCT_BUNDLE_DIR=$(BUNDLE_DIR) uv run python -m agentic_survey.bundles

deploy-config:
	docker compose -f deploy/coolify/docker-compose.yml config
