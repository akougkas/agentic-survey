from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from agentic_survey.admin_surfaces import ADMIN_SURFACES, is_known_surface
from agentic_survey.domain.outline import (
    DecisionGate,
    MicroFormField,
    OutlineArtifact,
    OutlineRubric,
    ParticipantFAQEntry,
    RiskEntry,
    SurveyQuestion,
)

_MODULE_ANCESTORS = Path(__file__).resolve().parents
# Dev tree: services/api/agentic_survey/bundles.py → parents[3] is the repo root.
# Container (/app/agentic_survey/bundles.py): truncated, fall back to the
# nearest ancestor that contains an examples/ dir, else to the module parent.
REPO_ROOT = _MODULE_ANCESTORS[3] if len(_MODULE_ANCESTORS) > 3 else _MODULE_ANCESTORS[-1]
DEFAULT_BUNDLE_RELATIVE_PATH = Path("examples") / "product-bundles" / "demo"


class CampaignReference(BaseModel):
    slug: str
    seed: str


class BundleBranding(BaseModel):
    eyebrow: str = "Agentic Survey"
    title: str = "Structured interview campaigns with Mira."
    description: str = (
        "Design a campaign, invite participants, and review the transcript and signal in one runtime."
    )


class BundleHomeCopy(BaseModel):
    eyebrow: str = "Operator Console"
    operator_path_label: str = "Operator path"
    operator_path_title: str = "Design a campaign"
    operator_path_description: str = "Begin with Mira, define objectives, and shape the first outline."
    participant_path_label: str = "Participant path"
    participant_path_title: str = "Resume a session"
    participant_path_description: str = (
        "Participants redeem an invitation, choose consent, and enter the interview loop."
    )
    bundle_panel_title: str = "Mounted bundle"
    persona_panel_title: str = "Mira"
    persona_panel_description: str = (
        "A synthetic field researcher with a measured voice, sharp memory, and no appetite for vague answers."
    )


class BundleAdminCopy(BaseModel):
    nav_label: str = "Workspace"
    workspace_eyebrow: str = "Operator Workspace"
    workspace_title: str = "Campaign workflow"
    login_eyebrow: str = "Operator Access"
    login_description: str = (
        "Access stays behind the environment variable gate. The default remains `change-me` until you replace it."
    )
    boundary_eyebrow: str = "Operator boundary"
    boundary_description: str = (
        "Admin access stays behind the runtime password gate. Product identity, seed campaigns, and deployment config come from the mounted bundle instead of the shared UI shell."
    )
    current_path_label: str = "Current path"
    current_path_description: str = (
        "Sign in, review campaigns, launch seeded studies, move drafts live, and inspect participant transcripts from the same workspace."
    )
    surfaces: list[str] | None = None

    @field_validator("surfaces", mode="before")
    @classmethod
    def validate_surfaces(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        canonical = ", ".join(ADMIN_SURFACES)
        if not isinstance(value, list) or len(value) == 0:
            raise ValueError(
                f"ui.admin.surfaces must be a non-empty list of known surface keys: {canonical}"
            )

        seen: set[str] = set()
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(
                    f"ui.admin.surfaces entries must be strings from the known surface keys: {canonical}"
                )
            if not is_known_surface(item):
                raise ValueError(
                    f"Unknown admin surface '{item}' in ui.admin.surfaces. Known surfaces: {canonical}"
                )
            if item not in seen:
                normalized.append(item)
                seen.add(item)
        return normalized


class BundleInviteCopy(BaseModel):
    header_eyebrow: str = "Research Conversation"
    header_wordmark: str = ""
    header_subline: str = ""
    page_title: str = "Research conversation invite"
    consent_title: str = "Before we begin"
    anonymous_title: str = "Contribute anonymously"
    anonymous_description: str = (
        "Your responses contribute to the analysis without attaching your name."
    )
    named_title: str = "Attribute your responses"
    named_description: str = (
        "Your name or preferred citation can appear alongside quoted responses in the resulting research outputs."
    )
    micro_form_eyebrow: str = "Orient Mira before you begin"
    micro_form_description: str = (
        "A sentence or two so Mira opens in a register that fits your work."
    )
    micro_form_required_hint: str = "This one is required before the conversation can begin."
    micro_form_answer_note: str = "Your answer stays between you, Mira, and the study team."
    start_button_idle: str = "Begin the conversation"
    start_button_pending: str = "Starting the session..."
    next_eyebrow: str = "How the conversation runs"
    next_steps: list[str] = Field(
        default_factory=lambda: [
            "Mira opens with one precise question grounded in what you shared above.",
            "Each answer is graded silently for coverage and follow-up signal.",
            "You can skip, pause, come back later, or stop at any point.",
        ]
    )
    closed_title: str = "This invitation is no longer active."
    closed_status_eyebrow: str = "Status"
    closed_status_template: str = 'This invite is marked "{status}" in the study.'
    closed_used_message: str = (
        "This invitation has already been redeemed. Each link is single-use."
    )
    closed_revoked_message: str = "This invitation has been withdrawn by the study team."
    closed_fresh_link_message: str = (
        "Contact the study team if you still need access."
    )


class BundleChatCopy(BaseModel):
    header_eyebrow: str = "Research Conversation"
    header_wordmark: str = ""
    header_subline: str = ""
    page_title: str = "Research conversation with Mira"
    conversation_heading: str = "Conversation"
    transcript_locked_label: str = "Transcript locked"
    agent_composing_label: str = "Mira is thinking..."
    working_notes_eyebrow: str = "Mira's working notes"
    working_notes_heading: str = "What I am tracking this session"
    retrieved_heading: str = "Retrieved this turn"
    retrieved_description_singular: str = (
        "Mira drew one passage from the study's grounding library."
    )
    retrieved_description_plural: str = (
        "Mira drew {count} passages from the study's grounding library."
    )
    concepts_heading: str = "Emerging concepts"
    concepts_empty: str = "Mira will name concepts as they surface in your answers."
    turn_counter_template: str = (
        "Turn {count}. This is an open-ended conversation with no fixed length."
    )
    active_footer: str = (
        "Answer in your own words. Mira keeps the thread focused one question at a time."
    )
    paused_footer: str = (
        "Mira has paused this session. Resume when you are ready to continue."
    )
    finished_footer: str = (
        "Mira has closed this session. The transcript is now read-only."
    )
    session_complete_eyebrow: str = "Session complete"
    return_home_label: str = "Return to home"
    empty_state: str = (
        "The conversation will begin with Mira's first question as soon as the session is ready."
    )
    placeholder_default: str = "Answer in your own words."
    placeholder_with_chips: str = "Tap one of the anchors above, or write your own answer."
    submit_idle: str = "Send"
    submit_pending: str = "Working..."
    submit_finished: str = "Session complete"
    thinking_messages: list[str] = Field(
        default_factory=lambda: [
            "Thinking...",
            "Holding your last answer in working memory...",
            "Tracing your last move through the rubric...",
            "Reading between your lines...",
            "Searching the knowledge corpus...",
            "Cross-checking what other researchers have said about this...",
            "Synthesizing the next question...",
            "Choosing the path that learns most from your next answer...",
            "Still here. Local-first means slow but methodical...",
        ]
    )


class BundleFooterCopy(BaseModel):
    """Quiet credits rendered under the participant chrome only.

    Operator (admin) routes never render this; the footer is participant-
    facing study credit (host institutions, developer attribution,
    copyright). All three lines are optional — empty strings are simply
    omitted at render time so a bundle can opt out of any one without
    leaking layout artifacts.
    """

    hosted_by: str = ""
    developed_by: str = ""
    copyright: str = ""


class BundleCopy(BaseModel):
    home: BundleHomeCopy = Field(default_factory=BundleHomeCopy)
    admin: BundleAdminCopy = Field(default_factory=BundleAdminCopy)
    invite: BundleInviteCopy = Field(default_factory=BundleInviteCopy)
    chat: BundleChatCopy = Field(default_factory=BundleChatCopy)
    footer: BundleFooterCopy = Field(default_factory=BundleFooterCopy)


class ProductBundleManifest(BaseModel):
    slug: str
    name: str
    runtime: str = "agentic-survey"
    public_base_url: str = ""
    branding: BundleBranding = Field(default_factory=BundleBranding)
    ui: BundleCopy = Field(default_factory=BundleCopy)
    campaigns: list[CampaignReference] = Field(default_factory=list)


class CampaignSeedOutline(BaseModel):
    research_question: str = ""
    sampling_frame: str = ""
    exclusion_criteria: str = ""
    publication_intent: str = ""
    axes: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    probes: list[str] = Field(default_factory=list)
    question_bank: list[SurveyQuestion] = Field(default_factory=list)
    risk_register: list[RiskEntry] = Field(default_factory=list)
    grounding_sources_approved: list[str] = Field(default_factory=list)
    readiness_rationale: str = ""
    decision_gate: DecisionGate | None = None
    suggested_search_queries: list[str] = Field(default_factory=list)
    rubric: OutlineRubric = Field(default_factory=OutlineRubric)
    freshness_query: str = ""
    persona_hints: dict[str, str] = Field(default_factory=dict)
    consent_language: str = ""
    micro_form_schema: list[MicroFormField] = Field(default_factory=list)
    scientist_summary: str = ""
    study_context: str = ""
    market_context: str = ""
    technical_context: str = ""
    aggregate_graph_context: str = ""
    participant_faq: list[ParticipantFAQEntry] = Field(default_factory=list)


SeedSourceKind = Literal["url", "pdf", "raw_text"]


class SeedSource(BaseModel):
    """Bundle-declared grounding source that M4 ingests as `knowledge_source`.

    `url` is required for `kind=url|pdf`; `content_inline` is required for
    `kind=raw_text`. The loader parses and surfaces the entries; the worker
    pipeline (M4) will materialize them as `pending_approval` rows.
    """

    kind: SeedSourceKind
    title: str
    url: str | None = None
    content_inline: str | None = None
    rationale: str = ""

    @model_validator(mode="after")
    def validate_kind_fields(self) -> "SeedSource":
        if self.kind in {"url", "pdf"}:
            if not self.url:
                raise ValueError(f"seed_source kind='{self.kind}' requires a url")
        elif self.kind == "raw_text":
            if not self.content_inline:
                raise ValueError("seed_source kind='raw_text' requires content_inline")
        return self


class CampaignSeed(BaseModel):
    slug: str
    title: str
    description: str = ""
    min_n: int = Field(ge=1)
    max_n: int = Field(ge=1)
    outline: CampaignSeedOutline = Field(default_factory=CampaignSeedOutline)
    seed_sources: list[SeedSource] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_bounds(self) -> "CampaignSeed":
        if self.max_n < self.min_n:
            raise ValueError("max_n must be greater than or equal to min_n")
        return self


class ActiveBundle(BaseModel):
    manifest: ProductBundleManifest
    campaigns: list[CampaignSeed] = Field(default_factory=list)


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def resolve_bundle_dir(bundle_dir: Path | None = None) -> Path:
    if bundle_dir is not None:
        return bundle_dir.expanduser().resolve()
    from agentic_survey.config import get_settings

    configured = get_settings().product_bundle_dir.strip()
    if configured:
        return Path(configured).expanduser().resolve()

    candidates = [
        (REPO_ROOT / DEFAULT_BUNDLE_RELATIVE_PATH).resolve(),
        (Path.cwd() / DEFAULT_BUNDLE_RELATIVE_PATH).resolve(),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_bundle_manifest(bundle_dir: Path | None = None) -> ProductBundleManifest:
    resolved_bundle_dir = resolve_bundle_dir(bundle_dir)
    manifest_path = resolved_bundle_dir / "product.yaml"
    return ProductBundleManifest.model_validate(_read_yaml(manifest_path))


def resolve_public_base_url(
    manifest: ProductBundleManifest,
    *,
    forwarded_public_base_url: str = "",
    configured_public_base_url: str = "",
    frontend_origin: str = "",
    request_base_url: str = "",
) -> str:
    for candidate in (
        forwarded_public_base_url,
        configured_public_base_url,
        manifest.public_base_url,
        frontend_origin,
        request_base_url,
    ):
        normalized = candidate.strip()
        if normalized:
            return normalized.rstrip("/")
    return ""


def load_campaign_seed(campaign_slug: str, *, bundle_dir: Path | None = None) -> CampaignSeed:
    resolved_bundle_dir = resolve_bundle_dir(bundle_dir)
    manifest = load_bundle_manifest(resolved_bundle_dir)
    reference = next(
        (item for item in manifest.campaigns if item.slug == campaign_slug),
        None,
    )
    if reference is None:
        raise FileNotFoundError(f"Campaign seed '{campaign_slug}' is not declared in {resolved_bundle_dir}")
    seed_path = resolved_bundle_dir / reference.seed
    return CampaignSeed.model_validate(_read_yaml(seed_path))


def list_campaign_seeds(bundle_dir: Path | None = None) -> list[CampaignSeed]:
    resolved_bundle_dir = resolve_bundle_dir(bundle_dir)
    manifest = load_bundle_manifest(resolved_bundle_dir)
    return [load_campaign_seed(reference.slug, bundle_dir=resolved_bundle_dir) for reference in manifest.campaigns]


def load_active_bundle(bundle_dir: Path | None = None) -> ActiveBundle:
    resolved_bundle_dir = resolve_bundle_dir(bundle_dir)
    return ActiveBundle(
        manifest=load_bundle_manifest(resolved_bundle_dir),
        campaigns=list_campaign_seeds(resolved_bundle_dir),
    )


def materialize_outline(seed: CampaignSeed) -> OutlineArtifact:
    outline = seed.outline
    return OutlineArtifact(
        research_question=outline.research_question,
        sampling_frame=outline.sampling_frame,
        exclusion_criteria=outline.exclusion_criteria,
        publication_intent=outline.publication_intent,
        axes=list(outline.axes),
        objectives=list(outline.objectives),
        probes=list(outline.probes),
        question_bank=[question.model_copy(deep=True) for question in outline.question_bank],
        risk_register=[entry.model_copy(deep=True) for entry in outline.risk_register],
        grounding_sources_approved=list(outline.grounding_sources_approved),
        readiness_rationale=outline.readiness_rationale,
        decision_gate=outline.decision_gate.model_copy(deep=True) if outline.decision_gate else None,
        suggested_search_queries=list(outline.suggested_search_queries),
        min_n=seed.min_n,
        max_n=seed.max_n,
        rubric=outline.rubric.model_copy(deep=True),
        freshness_query=outline.freshness_query,
        persona_hints=dict(outline.persona_hints),
        consent_language=outline.consent_language,
        micro_form_schema=[field.model_copy(deep=True) for field in outline.micro_form_schema],
        scientist_summary=outline.scientist_summary,
        study_context=outline.study_context,
        market_context=outline.market_context,
        technical_context=outline.technical_context,
        aggregate_graph_context=outline.aggregate_graph_context,
        participant_faq=[entry.model_copy(deep=True) for entry in outline.participant_faq],
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="Validate and print an Agentic Survey product bundle.")
    parser.add_argument("--bundle-dir", default="", help="Path to the bundle directory.")
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir).expanduser().resolve() if args.bundle_dir else None
    manifest = load_bundle_manifest(bundle_dir)
    seeds = list_campaign_seeds(bundle_dir)
    payload = {
        "bundle_dir": str(resolve_bundle_dir(bundle_dir)),
        "manifest": manifest.model_dump(),
        "campaigns": [seed.model_dump() for seed in seeds],
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    _main()
