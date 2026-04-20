"""M5: turn Validator concept/relation extraction into knowledge-graph writes.

The interview loop calls :func:`apply_validator_to_graph` after the
Validator has run on a participant turn and before Brain B runs for the
agent response. Concepts become ``concept`` rows (idempotent per
(campaign, normalized label)); their pairwise co-occurrences become
``mentioned_with`` edges with ``kind="co_occurrence"``; explicit
relations from ``extracted_relations`` become either
``mentioned_with``-with-``kind="explicit_relation"`` or ``contradicts``
edges.

Invariant, per `.claude/CLAUDE.md`: no try/except around embeddings or
Surreal writes. Failures bubble to the route so the operator sees them.
Cosmetic lookups belong elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from agentic_survey.repository import Concept, _normalize_concept_label

__all__ = ["GraphDelta", "apply_validator_to_graph"]


@dataclass(slots=True)
class GraphDelta:
    """Per-turn diff sent to the SSE event log.

    ``add_nodes`` lists only newly-created concepts (``is_new=True`` from
    the merge); ``add_edges`` lists every edge recorded this turn, in the
    order they were written; ``light_up`` is the set of concept ids
    touched by this turn, including re-mentions.
    """

    add_nodes: list[dict] = field(default_factory=list)
    add_edges: list[dict] = field(default_factory=list)
    light_up: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "add_nodes": list(self.add_nodes),
            "add_edges": list(self.add_edges),
            "light_up": list(self.light_up),
        }


async def apply_validator_to_graph(
    *,
    campaign_id: str,
    session_id: str,
    turn_id: str,
    validation: dict,
    repository,
    router,
) -> GraphDelta:
    """Write the graph side-effects implied by one Validator result.

    Steps (deterministic, in order):

    1. Normalize extracted concept labels and drop empty/duplicate ones.
    2. ``merge_concept`` each remaining label; embed on first insert.
    3. Emit ``C(n, 2)`` co-occurrence edges across the distinct concepts
       seen this turn.
    4. Apply each explicit relation: resolve both sides (merging if they
       were not in the concept list), then either
       ``record_contradicts`` or ``record_mentioned_with`` with
       ``kind="explicit_relation"``.
    """
    raw_concepts = validation.get("extracted_concepts") or []
    raw_relations = validation.get("extracted_relations") or []

    # Step 1 + 2: merge unique concepts in deterministic order.
    merged_by_label: dict[str, Concept] = {}
    ordered_labels: list[str] = []
    for entry in raw_concepts:
        if not isinstance(entry, dict):
            continue
        raw_label = entry.get("label")
        if not isinstance(raw_label, str):
            continue
        stripped = raw_label.strip()
        if not stripped:
            continue
        normalized = _normalize_concept_label(stripped)
        if normalized in merged_by_label:
            continue
        concept_type = str(entry.get("type") or "")
        concept = await repository.merge_concept(
            campaign_id=campaign_id,
            label=stripped,
            type=concept_type,
            router=router,
        )
        merged_by_label[normalized] = concept
        ordered_labels.append(normalized)

    add_nodes: list[dict] = [
        {
            "id": concept.id,
            "label": concept.label,
            "type": concept.type,
            "is_new": True,
        }
        for concept in (merged_by_label[label] for label in ordered_labels)
        if concept.is_new
    ]
    light_up: list[str] = [merged_by_label[label].id for label in ordered_labels]

    # Step 3: C(n, 2) co-occurrence edges across the distinct concepts.
    add_edges: list[dict] = []
    for left, right in combinations(ordered_labels, 2):
        from_id = merged_by_label[left].id
        to_id = merged_by_label[right].id
        repository.record_mentioned_with(
            campaign_id=campaign_id,
            session_id=session_id,
            turn_id=turn_id,
            from_id=from_id,
            to_id=to_id,
            kind="co_occurrence",
            confidence=1.0,
        )
        add_edges.append(
            {
                "from": from_id,
                "to": to_id,
                "kind": "co_occurrence",
                "edge_table": "mentioned_with",
                "confidence": 1.0,
            }
        )

    # Step 4: explicit relations from the Validator output.
    for relation in raw_relations:
        if not isinstance(relation, dict):
            continue
        from_raw = relation.get("from")
        to_raw = relation.get("to")
        if not isinstance(from_raw, str) or not isinstance(to_raw, str):
            continue
        if not from_raw.strip() or not to_raw.strip():
            continue
        from_norm = _normalize_concept_label(from_raw)
        to_norm = _normalize_concept_label(to_raw)
        if from_norm == to_norm:
            continue
        from_concept = await _resolve_concept(
            merged_by_label,
            ordered_labels,
            repository=repository,
            router=router,
            campaign_id=campaign_id,
            raw_label=from_raw,
            normalized=from_norm,
            add_nodes=add_nodes,
            light_up=light_up,
        )
        to_concept = await _resolve_concept(
            merged_by_label,
            ordered_labels,
            repository=repository,
            router=router,
            campaign_id=campaign_id,
            raw_label=to_raw,
            normalized=to_norm,
            add_nodes=add_nodes,
            light_up=light_up,
        )
        kind = str(relation.get("kind") or "").strip().lower()
        confidence = _coerce_confidence(relation.get("confidence"))
        if kind == "contradicts":
            repository.record_contradicts(
                campaign_id=campaign_id,
                session_id=session_id,
                turn_id=turn_id,
                from_id=from_concept.id,
                to_id=to_concept.id,
                confidence=confidence,
            )
            add_edges.append(
                {
                    "from": from_concept.id,
                    "to": to_concept.id,
                    "kind": "contradicts",
                    "edge_table": "contradicts",
                    "confidence": confidence,
                }
            )
        else:
            repository.record_mentioned_with(
                campaign_id=campaign_id,
                session_id=session_id,
                turn_id=turn_id,
                from_id=from_concept.id,
                to_id=to_concept.id,
                kind="explicit_relation",
                confidence=confidence,
            )
            add_edges.append(
                {
                    "from": from_concept.id,
                    "to": to_concept.id,
                    "kind": "explicit_relation",
                    "edge_table": "mentioned_with",
                    "confidence": confidence,
                }
            )

    return GraphDelta(add_nodes=add_nodes, add_edges=add_edges, light_up=light_up)


async def _resolve_concept(
    merged_by_label: dict[str, Concept],
    ordered_labels: list[str],
    *,
    repository,
    router,
    campaign_id: str,
    raw_label: str,
    normalized: str,
    add_nodes: list[dict],
    light_up: list[str],
) -> Concept:
    """Defensive merge for relation endpoints not seen in the concept list."""
    existing = merged_by_label.get(normalized)
    if existing is not None:
        return existing
    concept = await repository.merge_concept(
        campaign_id=campaign_id,
        label=raw_label,
        type="",
        router=router,
    )
    merged_by_label[normalized] = concept
    ordered_labels.append(normalized)
    light_up.append(concept.id)
    if concept.is_new:
        add_nodes.append(
            {
                "id": concept.id,
                "label": concept.label,
                "type": concept.type,
                "is_new": True,
            }
        )
    return concept


def _coerce_confidence(raw: Any) -> float:
    # bool is an int subclass; reject it so True doesn't silently become 1.0.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 1.0
    value = float(raw)
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
