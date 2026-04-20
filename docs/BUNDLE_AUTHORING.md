# Bundle Authoring

Product bundles supply identity, branding, campaign seeds, and optional integration hooks. The runtime stays generic; everything product-specific lives in the bundle. This document covers fields the loader parses beyond the baseline shape in `docs/BUNDLES.md`.

## Layout

```
product.yaml                        # product-level manifest
campaigns/<slug>.yaml               # one file per campaign referenced in product.yaml
```

The loader source is `services/api/agentic_survey/bundles.py`. Validate any bundle locally with:

```bash
SURVEY_PRODUCT_BUNDLE_DIR=<path> \
  uv run python -m agentic_survey.bundles
```

## Per-campaign `seed_sources`

Campaign YAMLs may declare `seed_sources:` to pre-ingest grounding material at campaign creation. Each entry surfaces to the M4 worker as a `knowledge_source(kind="bundle_seed", status="pending_approval")` row; the scientist approves or rejects in the first Designer session. Bundle seeds never auto-approve.

Fields:

| Field            | Type                            | Required                         | Notes                                              |
| ---------------- | ------------------------------- | -------------------------------- | -------------------------------------------------- |
| `kind`           | `url` \| `pdf` \| `raw_text`    | yes                              | Dispatches the downstream fetcher/extractor.       |
| `title`          | string                          | yes                              | Shown in the Knowledge rail.                       |
| `url`            | string                          | required when `kind=url` or `pdf`| Ignored for `raw_text`.                            |
| `content_inline` | string                          | required when `kind=raw_text`    | Literal payload; avoids network fetch.             |
| `rationale`      | string                          | no                               | Scientist-facing justification for the seed.       |

Example:

```yaml
seed_sources:
  - kind: url
    title: Seminal paper on trust calibration
    url: https://example.org/paper.html
    rationale: Seed literature for Axis 1 of the outline.
  - kind: raw_text
    title: Internal framing memo
    content_inline: |
      Baseline framing text pasted directly so no fetch is needed.
    rationale: Internal framing that is not publicly hosted.
```

## Backward compatibility

`seed_sources` is optional. Bundles authored before M4 load unchanged. The shipped demo bundle at `examples/product-bundles/demo/` declares none; seeded bundles such as `citadl/bundle/` exercise the field.
