from enum import StrEnum


class CampaignState(StrEnum):
    DRAFT = "draft"
    DESIGNING = "designing"
    REVIEWING = "reviewing"
    LIVE = "live"
    MONITORING = "monitoring"
    CLOSING = "closing"
    ARCHIVED = "archived"


ALLOWED_TRANSITIONS: dict[CampaignState, set[CampaignState]] = {
    CampaignState.DRAFT: {CampaignState.DESIGNING},
    CampaignState.DESIGNING: {CampaignState.REVIEWING},
    CampaignState.REVIEWING: {CampaignState.DESIGNING, CampaignState.LIVE},
    CampaignState.LIVE: {CampaignState.MONITORING, CampaignState.CLOSING, CampaignState.REVIEWING},
    CampaignState.MONITORING: {CampaignState.CLOSING, CampaignState.LIVE, CampaignState.REVIEWING},
    CampaignState.CLOSING: {CampaignState.ARCHIVED},
    CampaignState.ARCHIVED: set(),
}


class StateTransitionError(ValueError):
    pass


def can_transition(current: CampaignState, target: CampaignState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def transition_or_raise(current: CampaignState, target: CampaignState) -> CampaignState:
    if not can_transition(current, target):
        raise StateTransitionError(f"Illegal transition: {current} -> {target}")
    return target
