#!/usr/bin/env bash
# K-344 one-time infra setup — run with HUMAN permissions (SSO), not the agent
# lease, per the issue ("人の権限で初期設定"). Creates/updates:
#   s3://k344-prci-<acct>            artifact/result/evidence bucket
#   k344-prci-build-role             MicroVM image build
#   k344-prci-execution-role         deny-only exec role (for creds-free VM proof)
#   k344-prci-github-actions-role    OIDC CI role (trust = ci_trust.json)
# Idempotent: create-if-missing, always re-puts inline policies and the trust.
#
#   /Users/adachi/agent-skills/aws-sandbox-run/scripts/aws-sandbox-run \
#     --experiment-id 20261020-k344-001 --expires-at 2026-10-22 \
#     -- infra/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-ap-northeast-1}"
PROJECT="k344-prci"
OIDC_PROVIDER_HOST="token.actions.githubusercontent.com"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${PROJECT}-${ACCOUNT}"
OIDC_PROVIDER_ARN="arn:aws:iam::${ACCOUNT}:oidc-provider/${OIDC_PROVIDER_HOST}"
TAGS="Key=auto_delete,Value=${AUTO_DELETE:-true} Key=expires_at,Value=${EXPIRES_AT:-2026-10-22} Key=experiment_id,Value=${EXPERIMENT_ID:-20261020-k344-001} Key=owner,Value=adachi"

render() {  # render a policy template to stdout
  sed -e "s/@BUCKET@/${BUCKET}/g" \
      -e "s/@ACCOUNT@/${ACCOUNT}/g" \
      -e "s|@OIDC_PROVIDER_ARN@|${OIDC_PROVIDER_ARN}|g" "$1"
}

echo "== account: ${ACCOUNT} region: ${REGION} bucket: ${BUCKET}"

# --- bucket ---------------------------------------------------------------
if aws s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
  echo "bucket exists: ${BUCKET}"
else
  aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
    --create-bucket-configuration "LocationConstraint=${REGION}"
  echo "bucket created: ${BUCKET}"
fi
aws s3api put-public-access-block --bucket "${BUCKET}" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "${BUCKET}" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-lifecycle-configuration --bucket "${BUCKET}" --lifecycle-configuration '{
  "Rules": [
    {"ID":"expire-artifacts","Status":"Enabled","Filter":{"Prefix":"ci/"},"Expiration":{"Days":2}},
    {"ID":"expire-evidence","Status":"Enabled","Filter":{"Prefix":"evidence/"},"Expiration":{"Days":14}}
  ]}'
aws s3api put-bucket-tagging --bucket "${BUCKET}" --tagging "TagSet=[{Key=auto_delete,Value=${AUTO_DELETE:-true}},{Key=expires_at,Value=${EXPIRES_AT:-2026-10-22}},{Key=experiment_id,Value=${EXPERIMENT_ID:-20261020-k344-001}},{Key=owner,Value=adachi}]"

# --- OIDC provider must already exist -------------------------------------
if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "${OIDC_PROVIDER_ARN}" >/dev/null 2>&1; then
  echo "ERROR: OIDC provider ${OIDC_PROVIDER_ARN} missing; create it manually first" >&2
  exit 1
fi
echo "oidc provider present: ${OIDC_PROVIDER_ARN}"

ensure_role() {  # name, trust-file (rendered)
  local name="$1" trust="$2" rendered
  rendered="$(mktemp -t k344-trust)"
  render "${trust}" > "${rendered}"
  if aws iam get-role --role-name "${name}" >/dev/null 2>&1; then
    echo "role exists: ${name}"
  else
    aws iam create-role --role-name "${name}" \
      --assume-role-policy-document "file://${rendered}" \
      --tags ${TAGS} >/dev/null
    echo "role created: ${name}"
  fi
  rm -f "${rendered}"
}

ensure_role "${PROJECT}-build-role" infra/policies/microvm_service_trust.json
aws iam put-role-policy --role-name "${PROJECT}-build-role" \
  --policy-name microvm-build-policy \
  --policy-document "$(render infra/policies/build_role_policy.json)"

ensure_role "${PROJECT}-execution-role" infra/policies/microvm_service_trust.json
aws iam put-role-policy --role-name "${PROJECT}-execution-role" \
  --policy-name microvm-execution-minimal \
  --policy-document "$(render infra/policies/execution_role_policy.json)"

ensure_role "${PROJECT}-github-actions-role" infra/policies/ci_trust.json
aws iam update-assume-role-policy --role-name "${PROJECT}-github-actions-role" \
  --policy-document "$(render infra/policies/ci_trust.json)"
aws iam put-role-policy --role-name "${PROJECT}-github-actions-role" \
  --policy-name microvm-pr-ci-policy \
  --policy-document "$(render infra/policies/ci_role_policy.json)"

for r in build execution github-actions; do
  aws iam tag-role --role-name "${PROJECT}-${r}-role" \
    --tags Key=auto_delete,Value="${AUTO_DELETE:-true}" \
           Key=expires_at,Value="${EXPIRES_AT:-2026-10-22}" \
           Key=experiment_id,Value="${EXPERIMENT_ID:-20261020-k344-001}" \
           Key=owner,Value=adachi 2>/dev/null || true
done

mkdir -p infra
cat > infra/outputs.env <<EOF
ACCOUNT=${ACCOUNT}
REGION=${REGION}
ARTIFACT_BUCKET=${BUCKET}
BUILD_ROLE_ARN=arn:aws:iam::${ACCOUNT}:role/${PROJECT}-build-role
EXECUTION_ROLE_ARN=arn:aws:iam::${ACCOUNT}:role/${PROJECT}-execution-role
CI_ROLE_ARN=arn:aws:iam::${ACCOUNT}:role/${PROJECT}-github-actions-role
EOF
echo "== wrote infra/outputs.env"; cat infra/outputs.env
