from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from agentic_survey.repository import MicroFormField, OutlineArtifact, OutlineRubric, ParticipantFAQEntry

REPO_ROOT = Path(__file__).resolve().parents[3]
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


class BundleCopy(BaseModel):
    home: BundleHomeCopy = Field(default_factory=BundleHomeCopy)
    admin: BundleAdminCopy = Field(default_factory=BundleAdminCopy)


class ProductBundleManifest(BaseModel):
    slug: str
    name: str
    runtime: str = "agentic-survey"
    public_base_url: str = ""
    branding: BundleBranding = Field(default_factory=BundleBranding)
    ui: BundleCopy = Field(default_factory=BundleCopy)
    campaigns: list[CampaignReference] = Field(default_factory=list)


class CampaignSeedRubric(BaseModel):
    coverage_dimensions: list[str] = Field(default_factory=list)
    risk_checks: list[str] = Field(default_factory=list)


class CampaignSeedOutline(BaseModel):
    objectives: list[str] = Field(default_factory=list)
    probes: list[str] = Field(default_factory=list)
    rubric: CampaignSeedRubric
    freshness_query: str
    persona_hints: dict[str, str] = Field(default_factory=dict)
    consent_language: str
    micro_form_schema: list[MicroFormField] = Field(default_factory=list)
    scientist_summary: str = ""
    study_context: str = ""
    market_context: str = ""
    technical_context: str = ""
    aggregate_graph_context: str = ""
    participant_faq: list[ParticipantFAQEntry] = Field(default_factory=list)


class CampaignSeed(BaseModel):
    slug: str
    title: str
    description: str = ""
    min_n: int = Field(ge=1)
    max_n: int = Field(ge=1)
    outline: CampaignSeedOutline

    @model_validator(mode="after")
    def validate_bounds(self) -> "CampaignSeed":
        if self.max_n < self.min_n:
            raise ValueError("max_n must be greater than or equal to min_n")
        return self


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


def materialize_outline(seed: CampaignSeed) -> OutlineArtifact:
    return OutlineArtifact(
        objectives=list(seed.outline.objectives),
        probes=list(seed.outline.probes),
        rubric=OutlineRubric.model_validate(seed.outline.rubric.model_dump()),
        min_n=seed.min_n,
        max_n=seed.max_n,
        freshness_query=seed.outline.freshness_query,
        persona_hints=dict(seed.outline.persona_hints),
        consent_language=seed.outline.consent_language,
        micro_form_schema=[field.model_copy(deep=True) for field in seed.outline.micro_form_schema],
        scientist_summary=seed.outline.scientist_summary,
        study_context=seed.outline.study_context,
        market_context=seed.outline.market_context,
        technical_context=seed.outline.technical_context,
        aggregate_graph_context=seed.outline.aggregate_graph_context,
        participant_faq=[entry.model_copy(deep=True) for entry in seed.outline.participant_faq],
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
