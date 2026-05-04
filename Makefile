ROOT_DIR := $(abspath .)
API_HOST ?= 127.0.0.1
API_PORT ?= 8100
WEB_HOST ?= 127.0.0.1
WEB_PORT ?= 5270
WEB_PUBLIC_BASE_URL ?= http://$(WEB_HOST):$(WEB_PORT)
API_PROXY_TARGET ?= http://$(API_HOST):$(API_PORT)

.PHONY: api-dev api-dev-citadl api-test web-dev web-build web-check bundle-validate bundle-validate-citadl schema-apply verify

api-dev:
	cd services/api && SURVEY_PUBLIC_BASE_URL=$(WEB_PUBLIC_BASE_URL) SURVEY_FRONTEND_ORIGIN=$(WEB_PUBLIC_BASE_URL) uv run uvicorn agentic_survey.main:app --reload --host $(API_HOST) --port $(API_PORT)

api-dev-citadl:
	cd services/api && SURVEY_PRODUCT_BUNDLE_DIR=$(ROOT_DIR)/citadl/bundle SURVEY_PUBLIC_BASE_URL=$(WEB_PUBLIC_BASE_URL) SURVEY_FRONTEND_ORIGIN=$(WEB_PUBLIC_BASE_URL) uv run uvicorn agentic_survey.main:app --reload --host $(API_HOST) --port $(API_PORT)

api-test:
	cd services/api && uv run pytest

web-dev:
	cd apps/web && SURVEY_API_PROXY_TARGET=$(API_PROXY_TARGET) npm run dev -- --host $(WEB_HOST) --port $(WEB_PORT)

web-build:
	cd apps/web && npm run build

web-check:
	cd apps/web && npm run check

bundle-validate:
	cd services/api && uv run python -m agentic_survey.bundles

bundle-validate-citadl:
	cd services/api && SURVEY_PRODUCT_BUNDLE_DIR=$(ROOT_DIR)/citadl/bundle uv run python -m agentic_survey.bundles

schema-apply:
	cd services/api && uv run python -m agentic_survey.db.schema

verify: bundle-validate api-test web-check web-build
