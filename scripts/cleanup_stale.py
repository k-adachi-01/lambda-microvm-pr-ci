"""Sweep orphaned MicroVMs and stale S3 CI objects for K-344.

- Terminate any microVM whose state is not TERMINATED and whose age exceeds
  --max-age-minutes (default: matches the orchestrator's 900s VM cap).
- Delete ci/ S3 objects older than --s3-max-age-days.

Runs with ambient credentials (CI role in the sweeper workflow, or the lease).
Prints a JSON summary for the evidence record.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = "ap-northeast-1"
NOT_FOUND_CODES = {"ResourceNotFoundException", "ResourceNotFound", "NotFound"}


def parse_time(value):
    """Normalise the list API's timestamp field (boto3 datetime or ISO string)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bucket", required=True)
    p.add_argument("--region", default=REGION)
    p.add_argument("--image-arn", default=None,
                   help="only sweep VMs of this image (the sandbox hosts other experiments)")
    p.add_argument("--max-age-minutes", type=float, default=20)
    p.add_argument("--s3-max-age-days", type=float, default=2)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    session = boto3.Session(region_name=args.region)
    cfg = Config(retries={"max_attempts": 4})
    vm = session.client("lambda-microvms", config=cfg)
    s3 = session.client("s3", config=cfg)

    now = datetime.now(timezone.utc)
    out = {"scannedAt": now.isoformat(), "vms": [], "s3Deleted": 0, "dryRun": args.dry_run}

    # --- microVM sweep -----------------------------------------------------
    cutoff = now - timedelta(minutes=args.max_age_minutes)
    paginator = vm.get_paginator("list_microvms")
    for page in paginator.paginate():
        for item in page.get("items", []):
            if args.image_arn and item.get("imageArn") != args.image_arn:
                continue
            mid = item.get("microvmId")
            state = item.get("state")
            # list-microvms exposes startedAt (not createdAt); get-microvm also
            # uses startedAt. Without this fallback every VM looks ageless and
            # the sweeper silently never terminates anything.
            started = parse_time(item.get("startedAt") or item.get("createdAt"))
            stale = started is not None and started < cutoff
            rec = {"microvmId": mid, "state": state, "startedAt": str(started), "stale": stale}
            if state != "TERMINATED" and stale:
                if not args.dry_run:
                    try:
                        vm.terminate_microvm(microvmIdentifier=mid)
                        rec["action"] = "terminated"
                        rec["stateAfter"] = "TERMINATED"
                    except ClientError as exc:
                        code = exc.response.get("Error", {}).get("Code")
                        if code in NOT_FOUND_CODES:
                            rec["action"] = "already-gone"
                            rec["stateAfter"] = "TERMINATED"
                        else:
                            rec["action"] = f"terminate-error: {code}"
                            rec["stateAfter"] = state
                    except Exception as exc:  # noqa: BLE001
                        rec["action"] = f"terminate-error: {exc}"
                        rec["stateAfter"] = state
                else:
                    rec["action"] = "would-terminate"
                    rec["stateAfter"] = state
            else:
                rec["stateAfter"] = state
            out["vms"].append(rec)

    # --- stale S3 objects ---------------------------------------------------
    s3cutoff = now - timedelta(days=args.s3_max_age_days)
    objs = s3.get_paginator("list_objects_v2").paginate(Bucket=args.bucket, Prefix="ci/")
    for page in objs:
        for o in page.get("Contents", []):
            if o["LastModified"] < s3cutoff:
                if not args.dry_run:
                    s3.delete_object(Bucket=args.bucket, Key=o["Key"])
                out["s3Deleted"] += 1

    # Report post-action state, not the pre-action snapshot: a VM we just
    # terminated must not be counted as still alive.
    alive = [v for v in out["vms"] if v.get("stateAfter", v["state"]) != "TERMINATED"]
    out["aliveVms"] = len(alive)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 1 if alive else 0


if __name__ == "__main__":
    sys.exit(main())
