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

step "create invite"
invite="$(json -X POST "$BASE/campaigns/${campaign_id}/invites" \
                -d '{"label":"smoke invite"}')"
echo "$invite" | jq '{id, token: (.token | .[0:12] + "...")}'
invite_token="$(echo "$invite" | jq -r '.token')"
[[ -n "$invite_token" && "$invite_token" != "null" ]] || fail "invite creation failed"

step "redeem invite (participant session)"
session="$(json -X POST "$BASE/invites/${invite_token}/redeem" \
                 -d '{"consent_mode":"anonymous","identity_label":""}')"
echo "$session" | jq '{session_id: .session.id, campaign_title}'
session_id="$(echo "$session" | jq -r '.session.id')"
[[ -n "$session_id" && "$session_id" != "null" ]] || fail "invite redemption failed"

step "start participant loop (opening turn)"
bundle_start="$(json -X POST "$BASE/sessions/${session_id}/start" -d '{}')"
echo "$bundle_start" | jq '{turn_count: (.session.turns | length)}'

step "done"
echo "smoke: PASS — campaign=${campaign_id} session=${session_id}"
echo "base: $BASE"
