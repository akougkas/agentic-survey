# Bundles

Agentic Survey loads product identity and seed material from a mounted bundle directory.

## Resolution Order

1. `SURVEY_PRODUCT_BUNDLE_DIR`
2. `examples/product-bundles/demo`

## Required Files

- `product.yaml`
- `campaigns/*.yaml` referenced from the manifest

## Validation

```bash
cd services/api
uv run python -m agentic_survey.bundles
SURVEY_PRODUCT_BUNDLE_DIR=../../citadl/bundle uv run python -m agentic_survey.bundles
```

## Current Bundles

- `examples/product-bundles/demo` - generic runtime demo
- `citadl/bundle` - in-repo Citadl product bundle
