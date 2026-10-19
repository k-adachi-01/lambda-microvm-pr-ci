#!/usr/bin/env bash
# K-344 comparison baseline: a minimal CodeBuild project that runs the same
# tests from the same source zip on S3. One-time setup via human SSO:
#   aws-sandbox-run ... -- infra/deploy-codebuild.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source infra/outputs.env

ROLE="k344-prci-codebuild-role"
PROJECT="k344-prci-compare"

# --- service role ----------------------------------------------------------
if ! aws iam get-role --role-name "${ROLE}" >/dev/null 2>&1; then
  aws iam create-role --role-name "${ROLE}" --assume-role-policy-document '{
    "Version":"2012-10-17","Statement":[{"Effect":"Allow",
    "Principal":{"Service":"codebuild.amazonaws.com"},"Action":"sts:AssumeRole"}]
  }' >/dev/null
  echo "role created: ${ROLE}"
fi
aws iam put-role-policy --role-name "${ROLE}" --policy-name k344-prci-codebuild --policy-document "{
  \"Version\":\"2012-10-17\",\"Statement\":[
    {\"Sid\":\"ReadSource\",\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:GetObjectVersion\",\"s3:ListBucket\"],
     \"Resource\":[\"arn:aws:s3:::${ARTIFACT_BUCKET}\",\"arn:aws:s3:::${ARTIFACT_BUCKET}/*\"]},
    {\"Sid\":\"Logs\",\"Effect\":\"Allow\",\"Action\":[\"logs:CreateLogGroup\",\"logs:CreateLogStream\",\"logs:PutLogEvents\"],
     \"Resource\":[\"arn:aws:logs:${REGION}:${ACCOUNT}:log-group:/aws/codebuild/${PROJECT}*\"]}
  ]}"
aws iam tag-role --role-name "${ROLE}" \
  --tags Key=auto_delete,Value="${AUTO_DELETE:-true}" Key=expires_at,Value="${EXPIRES_AT:-2026-10-22}" \
         Key=experiment_id,Value="${EXPERIMENT_ID:-20261020-k344-001}" Key=owner,Value=adachi 2>/dev/null || true

# --- project ---------------------------------------------------------------
PROJ=$(cat <<EOF
{
  "name": "${PROJECT}",
  "source": {"type": "S3", "location": "${ARTIFACT_BUCKET}/compare/source.zip", "buildspec": "buildspec.yml"},
  "artifacts": {"type": "NO_ARTIFACTS"},
  "environment": {
    "type": "LINUX_CONTAINER",
    "image": "aws/codebuild/standard:7.0",
    "computeType": "BUILD_GENERAL1_SMALL",
    "imagePullCredentialsType": "CODEBUILD"
  },
  "serviceRole": "arn:aws:iam::${ACCOUNT}:role/${ROLE}",
  "logsConfig": {"cloudWatchLogs": {"status": "ENABLED", "groupName": "/aws/codebuild/${PROJECT}"}},
  "timeoutInMinutes": 10,
  "queuedTimeoutInMinutes": 10,
  "tags": [
    {"key":"auto_delete","value":"${AUTO_DELETE:-true}"},
    {"key":"expires_at","value":"${EXPIRES_AT:-2026-10-22}"},
    {"key":"experiment_id","value":"${EXPERIMENT_ID:-20261020-k344-001}"},
    {"key":"owner","value":"adachi"}
  ]
}
EOF
)
if aws codebuild batch-get-projects --names "${PROJECT}" --query 'projects[0].name' --output text 2>/dev/null | grep -q "${PROJECT}"; then
  aws codebuild update-project --cli-input-json "${PROJ}" >/dev/null && echo "project updated: ${PROJECT}"
else
  aws codebuild create-project --cli-input-json "${PROJ}" >/dev/null && echo "project created: ${PROJECT}"
fi
echo "CODEBUILD_PROJECT=${PROJECT}" >> infra/outputs.env
