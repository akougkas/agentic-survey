from __future__ import annotations

from agentic_survey.domain.outline import OutlineArtifact

__all__ = ["unmet_minimums"]

RESEARCH_QUESTION_MIN_CHARS = 40
MIN_AXES = 3
MIN_PROBES = 3
MIN_RISK_REGISTER = 1
MAX_N_CEILING = 1000

_INCLUSION_HINTS = ("inclu", "who count", "who belong", "eligible", "qualifie")


def unmet_minimums(outline: OutlineArtifact) -> list[str]:
    """Return the list of unmet hard-floor minimums as English sentences.

    An empty list means the outline passes the hard floor. The checks stay
    pure functions; readiness policy (e.g., combining this with Brain B's
    self-report) lives one layer up in ``agents/designer.py``.
    """
    unmet: list[str] = []

    research_question = outline.research_question.strip()
    if not research_question:
        unmet.append(
            "Research question is missing — Mira needs the single sentence the interviews will test."
        )
    elif len(research_question) < RESEARCH_QUESTION_MIN_CHARS:
        unmet.append(
            "Research question is too thin (needs a claim the interviews can sharpen or break)."
        )

    sampling_frame = outline.sampling_frame.strip()
    if not sampling_frame:
        unmet.append(
            "Sampling frame is empty — Mira cannot tell who belongs in this study."
        )
    elif not any(hint in sampling_frame.lower() for hint in _INCLUSION_HINTS):
        unmet.append(
            "Sampling frame does not spell out inclusion criteria — name who counts as a signal respondent."
        )

    if not outline.exclusion_criteria.strip():
        unmet.append(
            "Exclusion criteria are empty — say who falls outside the frame (use 'none — intentional' to waive)."
        )

    if not outline.publication_intent.strip():
        unmet.append(
            "Publication intent is not set — choose the shape of evidence the study will produce."
        )

    if len(outline.axes) < MIN_AXES:
        unmet.append(
            "Axes of inquiry are too few — expand to at least three."
        )

    if len(outline.probes) < MIN_PROBES:
        unmet.append(
            "Probes are too few — write at least three interviewable probes."
        )

    if len(outline.risk_register) < MIN_RISK_REGISTER:
        unmet.append(
            "Risk register is empty — name at least one confound and its mitigation."
        )

    if outline.min_n < 1:
        unmet.append("Sample floor min_n must be at least 1.")
    elif outline.max_n < outline.min_n:
        unmet.append("Sample bounds are inverted — max_n must be at least min_n.")
    elif outline.max_n > MAX_N_CEILING:
        unmet.append(
            f"Sample ceiling max_n exceeds {MAX_N_CEILING}; tighten the frame before launch."
        )

    return unmet
