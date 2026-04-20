# Agents

The platform has four named agent roles. Two run in the foreground, two in the background.

## Campaign Designer

- Talks to the scientist during campaign creation.
- Grounds its suggestions through SearXNG during design time only.
- Produces a reviewable `outline.json`.

## Interviewer

- Talks to participants during live sessions.
- Uses retrieved SurrealDB knowledge only; it never calls the web live.
- Is pinned to one endpoint for the lifetime of a participant session.

### First-Campaign Persona

The initial Interviewer persona is **Mira**.

- **Role:** synthetic field researcher
- **Tone:** measured, lucid, slightly warm
- **Behavior:** asks one precise question at a time, summarizes signal before probing, and is explicit about uncertainty

## Validator

- Grades each participant answer.
- Decides whether deeper follow-up is needed.
- Extracts concepts and relations for the live knowledge graph in the same call.

## Analyst

- Runs after completed sessions and during campaign monitoring.
- Updates theme clusters, saturation metrics, and the campaign graph.
- Produces the final report artifacts when a campaign closes.

## Shared Primitive

Campaign Designer and Interviewer both use the same interview-loop primitive:

1. Plan the next turn.
2. Stream the question.
3. Capture the response.
4. Validate and extract concepts.
5. Persist the turn.
6. Update the graph.
7. Continue until objectives are covered or a hard stop is reached.
