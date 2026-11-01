#!/usr/bin/env bash
# CloudFormation half of the K-344 cleanup verification.
#
# delstack only sees CloudFormation stacks. K-344 is created with direct AWS
# CLI calls, so this script verifies that no K-344 stack exists (deleting it
# with delstack if one does) and scripts/verify_clean.py checks the direct-API
# resources that delstack cannot see.
#
#   AWS_PROFILE=aws-poc-sandbox scripts/delstack_check.sh | tee out/teardown/delstack.log
set -euo pipefail
cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-ap-northeast-1}"
VERSION="${DELSTACK_VERSION:-2.12.3}"
DELSTACK_BIN="${DELSTACK_BIN:-/tmp/delstack-${VERSION}/delstack}"
URL="https://github.com/go-to-k/delstack/releases/download/v${VERSION}/delstack_${VERSION}_Darwin_arm64.tar.gz"
SHA256="a92268a0255222e696c62669dbe0fec6660dfd2ae85aa52b5a55307184d31c7e"

if [ ! -x "$DELSTACK_BIN" ]; then
  mkdir -p "$(dirname "$DELSTACK_BIN")"
  tmp="$(mktemp -d)"
  curl -fsSL -o "${tmp}/delstack.tar.gz" "$URL"
  echo "${SHA256}  ${tmp}/delstack.tar.gz" | shasum -a 256 -c -
  tar xzf "${tmp}/delstack.tar.gz" -C "$(dirname "$DELSTACK_BIN")"
  rm -rf "$tmp"
fi

echo "== delstack"
"$DELSTACK_BIN" --version

echo "== CloudFormation stacks in ${REGION}"
stacks="$(aws cloudformation describe-stacks --region "$REGION" \
  --query 'Stacks[].StackName' --output text | tr '\t' '\n' | sed '/^$/d')"
printf '%s\n' "$stacks"

k344="$(printf '%s\n' "$stacks" | grep -i 'k344' || true)"
if [ -n "$k344" ]; then
  echo "== deleting K-344 stacks with delstack"
  args=(-r "$REGION" -f -y -n 3)
  while IFS= read -r stack; do
    [ -n "$stack" ] && args+=(-s "$stack")
  done <<< "$k344"
  "$DELSTACK_BIN" "${args[@]}"
else
  echo "delstack: no K-344 CloudFormation stacks to delete"
fi
