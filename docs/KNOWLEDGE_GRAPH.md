# Knowledge Graph

The knowledge graph is both a live participant artifact and a scientist-facing analysis surface.

## Live Overlay

- Validator extracts concepts and relations on each turn.
- New concepts merge into the campaign graph by embedding similarity.
- SSE pushes graph deltas to the participant UI.
- Shared concepts from other respondents receive distinct styling.

## Analysis View

- Scientists inspect the full graph after or during a campaign.
- Filters span theme, demographic signal, saturation tier, and time.
- Export targets include JSON, SVG, and Neo4j-compatible data.

## Storage

SurrealDB stores both nodes and edges, scoped by campaign:

- `concept`
- `mentioned_with`
- `contradicts`
- `part_of_cluster`
