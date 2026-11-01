"""Verify that no K-344 resources remain in the PoC Sandbox account.

delstack only sees CloudFormation stacks. K-344 is created with direct AWS CLI
calls (S3, IAM, Lambda MicroVMs), so this script checks both the delstack
territory and the direct-API resources that delstack cannot see.

Usage:
    AWS_PROFILE=aws-poc-sandbox uv run python scripts/verify_clean.py \
        --experiment-id 20261101-k344-reverify-001 --out out/teardown/verify-clean.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

EXPECTED_ACCOUNT = "155936382172"
ROLE_PREFIX = "k344-prci-"
IMAGE_NAME = "k344-ci"
BUCKET = f"k344-prci-{EXPECTED_ACCOUNT}"


def head_bucket(s3, bucket: str) -> dict:
    try:
        s3.head_bucket(Bucket=bucket)
        return {"exists": True}
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket", "NotFound"):
            return {"exists": False}
        return {"exists": None, "error": f"{code}: {exc}"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--region", default="ap-northeast-1")
    p.add_argument("--out", default=None)
    p.add_argument("--experiment-id", default=None)
    args = p.parse_args()

    session = boto3.Session(region_name=args.region)
    account = session.client("sts").get_caller_identity()["Account"]
    if account != EXPECTED_ACCOUNT:
        raise SystemExit(f"refusing: account {account} != {EXPECTED_ACCOUNT}")

    iam = session.client("iam")
    s3 = session.client("s3")
    vm = session.client("lambda-microvms")
    logs = session.client("logs")
    cfn = session.client("cloudformation")
    codebuild = session.client("codebuild")
    ecr = session.client("ecr")

    roles = [
        r["RoleName"]
        for r in iam.list_roles().get("Roles", [])
        if r["RoleName"].startswith(ROLE_PREFIX)
    ]
    bucket = head_bucket(s3, BUCKET)
    images = [
        i
        for i in vm.list_microvm_images().get("items", [])
        if i.get("imageArn", "").endswith(f":{IMAGE_NAME}")
    ]
    vms = [
        v
        for v in vm.list_microvms().get("items", [])
        if f":{IMAGE_NAME}" in v.get("imageArn", "")
    ]
    active_vms = [v for v in vms if v.get("state") != "TERMINATED"]
    log_groups = [
        g["logGroupName"]
        for g in logs.describe_log_groups(
            logGroupNamePrefix=f"/aws/lambda-microvms/{IMAGE_NAME}"
        ).get("logGroups", [])
    ]
    log_groups += [
        g["logGroupName"]
        for g in logs.describe_log_groups(
            logGroupNamePrefix="/aws/codebuild/k344-prci"
        ).get("logGroups", [])
    ]
    projects = [
        p for p in codebuild.list_projects().get("projects", []) if p.startswith("k344")
    ]
    repositories = [
        r["repositoryName"]
        for r in ecr.describe_repositories().get("repositories", [])
        if "k344" in r["repositoryName"]
    ]
    buckets = [
        b["Name"] for b in s3.list_buckets().get("Buckets", []) if "k344" in b["Name"]
    ]
    stacks = [
        {"name": s["StackName"], "status": s["StackStatus"]}
        for s in cfn.describe_stacks().get("Stacks", [])
        if "k344" in s["StackName"].lower()
    ]

    tagged = []
    if args.experiment_id:
        tagging = session.client("resourcegroupstaggingapi")
        tagged = [
            r["ResourceARN"]
            for r in tagging.get_resources(
                TagFilters=[{"Key": "experiment_id", "Values": [args.experiment_id]}]
            ).get("ResourceTagMappingList", [])
        ]

    result = {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "account": account,
        "region": args.region,
        "experimentId": args.experiment_id,
        "iamRoles": roles,
        "s3Bucket": {"name": BUCKET, **bucket},
        "microvmImages": [i.get("imageArn") for i in images],
        "microvmVms": [
            {"id": v.get("microvmId"), "state": v.get("state"), "image": v.get("imageArn")}
            for v in vms
        ],
        "activeMicrovmVms": [
            {"id": v.get("microvmId"), "state": v.get("state"), "image": v.get("imageArn")}
            for v in active_vms
        ],
        "logGroups": log_groups,
        "codebuildProjects": projects,
        "ecrRepositories": repositories,
        "s3BucketsMatchingK344": buckets,
        "cloudformationStacks": stacks,
        "taggedResources": tagged,
    }
    clean = (
        not roles
        and bucket.get("exists") is False
        and not images
        and not active_vms
        and not log_groups
        and not projects
        and not repositories
        and not buckets
        and not stacks
        and not tagged
    )
    result["clean"] = clean

    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        from pathlib import Path

        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n")
    print(text)
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
