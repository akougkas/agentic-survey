# Grounding

The platform uses a strict separation between ingestion and retrieval.

## Ingestion

- Design-time ingestion starts during the Campaign Designer conversation.
- The scientist can provide URLs, PDFs, and notes.
- SearXNG can suggest additional sources, but the scientist explicitly approves what becomes campaign knowledge.

## Freshness Loop

- Every live campaign has a `freshness_query`.
- Default cadence is daily at `03:00` server local time.
- Each run deduplicates, relevance-filters, chunks, embeds, and stores approved additions.

## Retrieval

- Retrieval is synchronous and SurrealDB-only.
- No live web calls happen inside participant turns.
- Every retrieved chunk is logged for later audit.

## Scientist Controls

- Review or quarantine freshness additions.
- Upload raw text, URLs, or PDFs manually.
- Edit the freshness query.
- Pause or resume freshness.
