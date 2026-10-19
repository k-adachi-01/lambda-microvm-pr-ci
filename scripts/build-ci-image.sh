#!/usr/bin/env bash
# Package ci/image into a zip, upload to the artifact bucket, and create/update
# the k344-ci MicroVM image. Run inside the lease:
#   scripts/lease -- scripts/build-ci-image.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source infra/outputs.env

IMAGE_NAME="${IMAGE_NAME:-k344-ci}"
ZIP="out/ci-image.zip"
mkdir -p out
rm -f "$ZIP"
(cd ci/image && zip -X -q -r "$OLDPWD/$ZIP" .)
aws s3 cp "$ZIP" "s3://${ARTIFACT_BUCKET}/artifacts/ci-image.zip" --region "$REGION"

IMAGE_ARN="arn:aws:lambda:${REGION}:${ACCOUNT}:microvm-image:${IMAGE_NAME}"
BASE="arn:aws:lambda:${REGION}:aws:microvm-image:al2023-1"
COMMON=(--code-artifact "uri=s3://${ARTIFACT_BUCKET}/artifacts/ci-image.zip"
        --base-image-arn "$BASE" --build-role-arn "$BUILD_ROLE_ARN")

if aws lambda-microvms get-microvm-image --image-identifier "$IMAGE_ARN" --region "$REGION" >/dev/null 2>&1; then
  aws lambda-microvms update-microvm-image --image-identifier "$IMAGE_ARN" "${COMMON[@]}" --region "$REGION"
else
  aws lambda-microvms create-microvm-image --name "$IMAGE_NAME" "${COMMON[@]}" --region "$REGION"
fi

echo "waiting for ${IMAGE_ARN}"
for i in $(seq 1 120); do
  state=$(aws lambda-microvms get-microvm-image --image-identifier "$IMAGE_ARN" --region "$REGION" --query 'state' --output text)
  echo "  [$i] state=$state"
  case "$state" in
    ACTIVE|CREATED) break ;;
    FAILED) aws lambda-microvms get-microvm-image --image-identifier "$IMAGE_ARN" --region "$REGION"; exit 1 ;;
  esac
  sleep 15
done
echo "CI_IMAGE_ARN=${IMAGE_ARN}"
