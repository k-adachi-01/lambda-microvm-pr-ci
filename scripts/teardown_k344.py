"""Delete the K-344 resources created by infra/deploy.sh and build-ci-image.sh.

This is intentionally narrow: only names under k344-prci-* / the k344-ci
MicroVM image / the k344-prci-<account> bucket are touched. CloudFormation
stacks are not deleted here; use scripts/delstack_check.sh (K-344 has none).

Usage:
    AWS_PROFILE=aws-poc-sandbox uv run python scripts/teardown_k344.py --apply \
        --out out/teardown/teardown.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

EXPECTED_ACCOUNT = "155936382172"
ROLE_PREFIX = "k344-prci-"
IMAGE_NAME = "k344-ci"
BUCKET = f"k344-prci-{EXPECTED_ACCOUNT}"


def is_not_found(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in {
        "ResourceNotFoundException",
        "ResourceNotFound",
        "NotFound",
        "NoSuchEntity",
        "404",
    }


def wait_image_gone(vm, arn: str, timeout: int = 180) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            vm.get_microvm_image(imageIdentifier=arn)
        except ClientError as exc:
            if is_not_found(exc):
                return "gone"
            return f"unverified: {exc.response.get('Error', {}).get('Code')}"
        time.sleep(3)
    return "still-present"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--region", default="ap-northeast-1")
    p.add_argument("--apply", action="store_true", help="actually delete (default: dry-run)")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    session = boto3.Session(region_name=args.region)
    account = session.client("sts").get_caller_identity()["Account"]
    if account != EXPECTED_ACCOUNT:
        raise SystemExit(f"refusing: account {account} != {EXPECTED_ACCOUNT}")

    vm = session.client("lambda-microvms")
    s3 = session.client("s3")
    iam = session.client("iam")
    logs = session.client("logs")
    codebuild = session.client("codebuild")

    out: dict = {
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "account": account,
        "region": args.region,
        "apply": args.apply,
        "actions": [],
    }

    def act(kind: str, target: str, result: str) -> None:
        out["actions"].append({"kind": kind, "target": target, "result": result})
        print(f"{kind}: {target}: {result}", flush=True)

    # 1. Running/leftover MicroVMs of our image
    for item in vm.list_microvms().get("items", []):
        if f":{IMAGE_NAME}" not in item.get("imageArn", ""):
            continue
        mid = item["microvmId"]
        if item.get("state") == "TERMINATED":
            act("vm", mid, "already TERMINATED")
            continue
        if not args.apply:
            act("vm", mid, f"would terminate ({item.get('state')})")
            continue
        try:
            vm.terminate_microvm(microvmIdentifier=mid)
            act("vm", mid, "terminate requested")
        except ClientError as exc:
            act("vm", mid, f"terminate failed: {exc}")

    # 2. MicroVM image (delete after VMs are gone)
    images = [
        i
        for i in vm.list_microvm_images().get("items", [])
        if i.get("imageArn", "").endswith(f":{IMAGE_NAME}")
    ]
    for image in images:
        arn = image["imageArn"]
        if not args.apply:
            act("image", arn, "would delete")
            continue
        try:
            vm.delete_microvm_image(imageIdentifier=arn)
            act("image", arn, f"delete requested; state={wait_image_gone(vm, arn)}")
        except ClientError as exc:
            act("image", arn, f"delete failed: {exc}")

    # 3. S3 bucket (objects first)
    try:
        s3.head_bucket(Bucket=BUCKET)
    except ClientError as exc:
        act("s3", BUCKET, f"already absent ({exc.response.get('Error', {}).get('Code')})")
    else:
        if not args.apply:
            act("s3", BUCKET, "would delete bucket and objects")
        else:
            for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
                keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
                if keys:
                    s3.delete_objects(Bucket=BUCKET, Delete={"Objects": keys})
            for page in s3.get_paginator("list_object_versions").paginate(Bucket=BUCKET):
                versions = [
                    {"Key": v["Key"], "VersionId": v["VersionId"]}
                    for v in page.get("Versions", []) + page.get("DeleteMarkers", [])
                ]
                if versions:
                    s3.delete_objects(Bucket=BUCKET, Delete={"Objects": versions})
            try:
                s3.delete_bucket(Bucket=BUCKET)
                act("s3", BUCKET, "bucket deleted")
            except ClientError as exc:
                act("s3", BUCKET, f"bucket delete failed: {exc}")

    # 4. IAM roles (inline policies first, then attached managed policies)
    for role in iam.list_roles().get("Roles", []):
        name = role["RoleName"]
        if not name.startswith(ROLE_PREFIX):
            continue
        if not args.apply:
            act("iam", name, "would delete role")
            continue
        try:
            for policy in iam.list_role_policies(RoleName=name).get("PolicyNames", []):
                iam.delete_role_policy(RoleName=name, PolicyName=policy)
            for policy in iam.list_attached_role_policies(RoleName=name).get(
                "AttachedPolicies", []
            ):
                iam.detach_role_policy(RoleName=name, PolicyArn=policy["PolicyArn"])
            iam.delete_role(RoleName=name)
            act("iam", name, "role deleted")
        except ClientError as exc:
            act("iam", name, f"role delete failed: {exc}")

    # 5. Log groups created by image builds / VM runs / the CodeBuild baseline
    prefixes = [f"/aws/lambda-microvms/{IMAGE_NAME}", "/aws/codebuild/k344-prci"]
    for prefix in prefixes:
        for group in logs.describe_log_groups(logGroupNamePrefix=prefix).get("logGroups", []):
            name = group["logGroupName"]
            if not args.apply:
                act("logs", name, "would delete")
                continue
            try:
                logs.delete_log_group(logGroupName=name)
                act("logs", name, "deleted")
            except ClientError as exc:
                act("logs", name, f"delete failed: {exc}")

    # 6. CodeBuild comparison project (created by infra/deploy-codebuild.sh)
    for project in codebuild.list_projects().get("projects", []):
        if not project.startswith("k344-prci"):
            continue
        if not args.apply:
            act("codebuild", project, "would delete")
            continue
        try:
            codebuild.delete_project(name=project)
            act("codebuild", project, "project deleted")
        except ClientError as exc:
            act("codebuild", project, f"delete failed: {exc}")

    out["finishedAt"] = datetime.now(timezone.utc).isoformat()
    text = json.dumps(out, indent=2, sort_keys=True)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
