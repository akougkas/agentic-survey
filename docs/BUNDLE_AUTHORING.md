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

## Product-level `research_agent_hook`

`product.yaml` may declare `research_agent_hook:` to wire an external deep-research service into Designer Brain B. When configured, Brain B gains a `request_deep_research` tool; results land as `knowledge_source(kind="deep_research_result", status="pending_approval")` awaiting scientist approval.

Fields:

| Field      | Type                 | Required | Notes                                                     |
| ---------- | -------------------- | -------- | --------------------------------------------------------- |
| `provider` | string \| null       | yes      | Adapter name. Only `null` ships in v1.                    |
| `config`   | mapping (opaque)     | no       | Passed through to the adapter verbatim; loader ignores.  |

Example:

```yaml
research_agent_hook:
  provider: "null"
  config:
    defaults:
      scope: standard
      depth: 3
```

### Resolver behavior

- Unset, or `provider: null` / `provider: "null"` resolves to `NullResearchAgent`: `dispatch` returns a typed handle, `status` returns `completed`, `fetch` returns an empty result with `rationale="No research agent configured"`.
- Any other provider string raises `NotImplementedError`. Adapters (OpenAI Deep Research, Perplexity, Exa, local agents) land post-v1 behind the same `ResearchAgentHook` Protocol.

The Protocol and types live in `services/api/agentic_survey/integrations/research_agent.py`.

## Backward compatibility

Both fields are optional. Bundles authored before M4 load unchanged. The shipped demo bundle at `examples/product-bundles/demo/` declares neither; the fixture at `examples/product-bundles/demo-with-seeds/` exercises both for loader tests.
