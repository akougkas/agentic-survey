#!/usr/bin/env bash
# End-to-end smoke for the agentic-survey deployment.
#
# Usage:
#   infra/ops/smoke.sh                                 # default http://localhost:8100/api
#   infra/ops/smoke.sh https://citadl.gnosis.run/api   # against blade
#
# Requires: curl, jq. Reads SURVEY_ADMIN_PASSWORD (default "change-me").
# Exits non-zero with a clear message on the first failure.

set -euo pipefail

BASE="${1:-http://localhost:8100/api}"
ADMIN_PASSWORD="${SURVEY_ADMIN_PASSWORD:-change-me}"
COOKIE_JAR="$(mktemp -t agentic-survey-smoke.XXXXXX)"
trap 'rm -f "$COOKIE_JAR"' EXIT

have() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "smoke: missing dependency '$1'"
        exit 2
    }
}
have curl
have jq

step() {
    printf '\n=== %s ===\n' "$1"
}

fail() {
    echo "smoke: $1" >&2
    exit 1
}

json() {
    curl -sS --cookie "$COOKIE_JAR" --cookie-jar "$COOKIE_JAR" \
         -H 'content-type: application/json' "$@"
}

step "healthz"
health="$(curl -sS "$BASE/healthz")"
echo "$health"
echo "$health" | jq -e '.status == "ok"' >/dev/null \
    || fail "healthz did not return status=ok"

step "system context (bundle + branding)"
ctx="$(curl -sS "$BASE/system/context")"
echo "$ctx" | jq '{bundle_slug, bundle_name, app_name, campaign_seed_count}'
seed_count="$(echo "$ctx" | jq -r '.campaign_seed_count // 0')"
[[ "$seed_count" -ge 1 ]] || fail "campaign_seed_count=$seed_count; bundle did not load"

step "admin login"
json -X POST "$BASE/admin/login" \
     -d "{\"password\":\"${ADMIN_PASSWORD}\"}" \
     | jq '{authenticated, expires_at}'

step "bundle catalog"
catalog="$(json "$BASE/campaigns/catalog")"
echo "$catalog" | jq '{bundle: .bundle.slug, seeds: [.seeds[].slug]}'
seed_slug="$(echo "$catalog" | jq -r '.seeds[0].slug // empty')"
[[ -n "$seed_slug" ]] || fail "no campaign seeds in catalog; check SURVEY_PRODUCT_BUNDLE_DIR"

step "create designer smoke campaign"
designer_campaign="$(json -X POST "$BASE/campaigns" \
                         -d '{"title":"Smoke designer path","min_n":3,"max_n":6}')"
designer_campaign_id="$(echo "$designer_campaign" | jq -r '.id')"
echo "designer_campaign_id=$designer_campaign_id"
[[ "$designer_campaign_id" != "null" && -n "$designer_campaign_id" ]] \
    || fail "designer smoke campaign creation returned no id"

step "designer start"
designer_start="$(json -X POST "$BASE/campaigns/${designer_campaign_id}/designer/start" -d '{}')"
echo "$designer_start" | jq '{designer_turns: (.designer_session.turns | length)}'

step "designer turn"
designer_turn="$(json -X POST "$BASE/campaigns/${designer_campaign_id}/designer/turns" \
                     -d '{"content":"Draft a compact study outline for a smoke test. Keep it generic and ready for review if enough detail is present."}')"
echo "$designer_turn" | jq '{state: .campaign.state, outline_status: .campaign.outline_status, designer_turns: (.designer_session.turns | length)}'

step "create campaign from seed: $seed_slug"
campaign="$(json -X POST "$BASE/campaigns/from-seed" \
                 -d "{\"seed_slug\":\"${seed_slug}\"}")"
campaign_id="$(echo "$campaign" | jq -r '.id')"
echo "campaign_id=$campaign_id"
[[ "$campaign_id" != "null" && -n "$campaign_id" ]] || fail "campaign creation returned no id"

step "knowledge sources (if seed_sources present)"
knowledge="$(json "$BASE/admin/campaigns/${campaign_id}/knowledge" || true)"
echo "$knowledge" | jq '{total, status_keys: (.by_status | keys)}' 2>/dev/null \
    || echo "  (no knowledge endpoint response; B2-min path may be disabled)"

step "advance campaign to live"
advanced="$(json -X POST "$BASE/campaigns/${campaign_id}/advance" \
                  -d '{"target_state":"live"}')"
advanced_state="$(echo "$advanced" | jq -r '.campaign.state // empty')"
echo "campaign_state=${advanced_state:-unknown}"
[[ "$advanced_state" == "live" ]] || fail "campaign did not advance to live (state=${advanced_state})"

step "create invite"
invite="$(json -X POST "$BASE/invites" \
                -d "{\"campaign_id\":\"${campaign_id}\",\"label\":\"smoke invite\"}")"
echo "$invite" | jq '{id, token: (.token | .[0:12] + "...")}'
invite_token="$(echo "$invite" | jq -r '.token')"
[[ -n "$invite_token" && "$invite_token" != "null" ]] || fail "invite creation failed"

step "redeem invite (participant session)"
session="$(json -X POST "$BASE/invites/${invite_token}/redeem" \
                 -d '{"consent_mode":"anonymous","identity_label":"","micro_form_answers":{"evidence_of_belonging":"I operate research data workflows for a smoke test.","role_self_description":"Facility operator or systems administrator"}}')"
echo "$session" | jq '{session_id: .session.id, campaign_title}'
session_id="$(echo "$session" | jq -r '.session.id')"
[[ -n "$session_id" && "$session_id" != "null" ]] || fail "invite redemption failed"

step "start participant loop (opening turn)"
bundle_start="$(json -X POST "$BASE/sessions/${session_id}/start" -d '{}')"
echo "$bundle_start" | jq '{turn_count: (.session.turns | length)}'

step "citadl admin surfaces allowlist"
ctx_latest="$(curl -sS "$BASE/system/context")"
bundle_slug="$(echo "$ctx_latest" | jq -r '.bundle_slug // empty')"
bundle_dir="${SURVEY_PRODUCT_BUNDLE_DIR:-}"
if [[ "$bundle_slug" == "citadl" || "$bundle_dir" == *"citadl/bundle"* ]]; then
    if echo "$ctx_latest" | jq -e '.admin_surfaces_allowlist == null' >/dev/null; then
        echo "admin_surfaces_allowlist=null; skipping bundle-specific assertion"
    else
        echo "$ctx_latest" | jq -e '.admin_surfaces_allowlist == ["catalog", "campaigns"]' >/dev/null \
            || fail "citadl admin_surfaces_allowlist is not [\"catalog\", \"campaigns\"]"
        echo "$ctx_latest" | jq '{admin_surfaces_allowlist}'
    fi
else
    echo "bundle_slug=${bundle_slug:-unknown}; skipping citadl-specific assertion"
fi

step "done"
echo "smoke: PASS: campaign=${campaign_id} session=${session_id}"
echo "base: $BASE"
