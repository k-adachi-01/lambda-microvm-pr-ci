"""Disposable-CI orchestrator: run one CI job on a fresh Lambda MicroVM.

Pipeline (all AWS calls use ambient credentials — the GitHub Actions OIDC role
or a local aws-agent-lease session):

  1. read the source artifact (tarball bytes or a packaged source dir),
     sha256 it, upload to s3://<bucket>/<key-prefix>/
  2. presign GET (artifact) and PUT (result bundle) URLs
  3. run-microvm on the fixed CI image, wait for RUNNING (throttle-aware retry)
  4. create-microvm-auth-token (port 8080), POST /job with the payload
  5. poll /job/status, fetch /job/result + /job/logs
  6. verify the in-VM PUT landed in S3
  7. terminate the MicroVM in a finally block; verify TERMINATED
     (SIGTERM/SIGINT also funnel through the finally so runner cancel = cleanup)

Exit code: 0 = job succeeded, 1 = job ran but failed, 2 = infra/protocol error.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import random
import signal
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = "ap-northeast-1"
CONNECTOR = "arn:aws:lambda:{r}:aws:network-connector:aws-network-connector:{name}"
THROTTLE_CODES = {
    "Throttling",
    "ThrottlingException",
    "TooManyRequestsException",
    "RequestLimitExceeded",
    "ServiceUnavailableException",
    # Backpressure, not a rate limit: the account's concurrent-microVM memory
    # quota was exceeded (measured 8 GiB; see K-346). VMs churn in seconds, so
    # bounded retry is the right behaviour for CI bursts.
    "ServiceQuotaExceededException",
}


def connector(region: str, name: str) -> str:
    return CONNECTOR.format(r=region, name=name)


def package_source_dir(source_dir: Path) -> tuple[bytes, str]:
    """tar.gz a directory deterministically; return (bytes, sha256)."""
    buf = io.BytesIO()
    gz = gzip.GzipFile(fileobj=buf, mode="wb", mtime=0)
    with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            info = tar.gettarinfo(str(path), arcname=str(path.relative_to(source_dir)))
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with open(path, "rb") as fh:
                tar.addfile(info, fh)
    gz.close()
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def package_tarball(tarball: Path, strip_components: int) -> tuple[bytes, str]:
    """Rewrite an upstream tarball (e.g. GitHub codeload) into a deterministic
    tar.gz with `strip_components` leading path elements removed — without
    extracting anything to the runner filesystem."""
    buf = io.BytesIO()
    gz = gzip.GzipFile(fileobj=buf, mode="wb", mtime=0)
    with tarfile.open(tarball, "r:*") as src, tarfile.open(
        fileobj=gz, mode="w", format=tarfile.PAX_FORMAT
    ) as dst:
        for member in src.getmembers():
            parts = Path(member.name).parts[strip_components:]
            if not parts:
                continue
            name = str(Path(*parts))
            if not member.isfile():
                continue
            info = tarfile.TarInfo(name)
            info.size = member.size
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = member.mode & 0o777
            fh = src.extractfile(member)
            if fh is None:
                continue
            with fh:
                dst.addfile(info, fh)
    gz.close()
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def request_json(method: str, url: str, token: str, payload=None, raw: bool = False, timeout: float = 60):
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"X-aws-proxy-auth": token, "X-aws-proxy-port": "8080", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - AWS-issued endpoint
        data = resp.read()
    return data if raw else (json.loads(data.decode()) if data else {})


def is_throttle(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in THROTTLE_CODES


def run_microvm_with_retry(vm, run_req: dict, attempts: int = 6) -> tuple[dict, list]:
    """RunMicrovm is rate-limited account-wide (K-346 measured an applied
    quota of 1 req/s here). Retry throttling with jittered backoff and record
    every attempt for evidence."""
    log = []
    delay = 1.0
    for i in range(1, attempts + 1):
        t0 = time.monotonic()
        try:
            resp = vm.run_microvm(**run_req)
            log.append({"attempt": i, "ok": True, "ms": round((time.monotonic() - t0) * 1000)})
            return resp, log
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            log.append({"attempt": i, "ok": False, "code": code,
                        "ms": round((time.monotonic() - t0) * 1000)})
            if not is_throttle(exc) or i == attempts:
                raise
            time.sleep(delay + random.random())
            delay = min(delay * 2, 20)
    raise RuntimeError("unreachable")


def wait_running(vm, microvm_id: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = vm.get_microvm(microvmIdentifier=microvm_id)
        if item["state"] == "RUNNING":
            return item
        if item["state"] in ("TERMINATED", "FAILED"):
            raise RuntimeError(f"VM entered {item['state']}")
        time.sleep(3)
    raise TimeoutError("VM did not reach RUNNING")


def wait_terminated(vm, microvm_id: str, timeout: int = 120) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = vm.get_microvm(microvmIdentifier=microvm_id)["state"]
        except Exception as exc:  # noqa: BLE001 - NotFound means gone
            return f"gone ({exc.__class__.__name__})"
        if state == "TERMINATED":
            return state
        time.sleep(3)
    return "still-not-TERMINATED"


def write_check_summary(out_dir: Path, summary: dict, result: dict | None) -> None:
    """Emit a compact markdown body used to update the GitHub Check run output."""
    meta = summary.get("metadata", {})
    lines = [
        f"### disposable microVM CI — `{summary.get('jobStatus', 'unknown')}`",
        "",
        "| field | value |",
        "|---|---|",
        f"| jobId | `{summary.get('jobId')}` |",
        f"| microvmId | `{summary.get('microvmId', 'n/a')}` |",
        f"| PR | `#{meta.get('pr', 'n/a')}` |",
        f"| head SHA | `{meta.get('head_sha', 'n/a')}` |",
        f"| run | `{meta.get('run_id', 'n/a')}` attempt `{meta.get('run_attempt', 'n/a')}` |",
        f"| artifact sha256 | `{summary.get('sha256', 'n/a')[:16]}…` |",
    ]
    t = summary.get("timings", {})
    if t:
        lines += ["", "**timings (s):** " + " ".join(f"{k}={v}" for k, v in t.items())]
    if result and result.get("steps"):
        lines += ["", "| step | exit | ms |", "|---|---|---|"]
        for s in result["steps"]:
            lines.append(f"| `{s['step']}` | {s['exitCode']} | {s['durationMs']} |")
    (out_dir / "check_summary.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bucket", required=True, help="artifact/result S3 bucket")
    p.add_argument("--image-identifier", required=True, help="microvm image ARN")
    p.add_argument("--image-version", default=None)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--source-dir", type=Path)
    src.add_argument("--source-tarball", type=Path, help="upstream .tar.gz (e.g. GitHub codeload)")
    p.add_argument("--strip-components", type=int, default=1,
                   help="leading path elements dropped when repacking --source-tarball")
    p.add_argument("--step", action="append", required=True, help="pipeline step (repeatable)")
    p.add_argument("--job-id", required=True)
    p.add_argument("--key-prefix", default="ci", help="S3 prefix for artifact+result objects")
    p.add_argument("--label", action="append", default=[], metavar="K=V",
                   help="metadata recorded in summary.json (repeatable)")
    p.add_argument("--artifact-sha256", default=None,
                   help="override the advertised artifact hash (negative test)")
    p.add_argument("--vm-id", default=None, help="reuse an already-running VM (skip run/terminate)")
    p.add_argument("--max-duration-seconds", type=int, default=900,
                   help="hard VM lifetime cap — orphan protection")
    p.add_argument("--job-timeout-seconds", type=int, default=600)
    p.add_argument("--token-minutes", type=int, default=15)
    p.add_argument("--out-dir", type=Path, default=None)
    p.add_argument("--region", default=REGION)
    p.add_argument("--boto-max-attempts", type=int, default=4,
                   help="botocore retry cap; 1 surfaces raw 429s for throttle experiments")
    p.add_argument("--run-attempts", type=int, default=6,
                   help="RunMicrovm throttle retries inside the orchestrator")
    args = p.parse_args()

    job_id = args.job_id
    out_dir = args.out_dir or Path("out/ci") / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    t_all = time.monotonic()

    # Runner cancel arrives as SIGTERM; route it through the finally below so
    # the MicroVM is still terminated (belt: maximumDurationInSeconds also caps
    # every VM; suspenders: scripts/cleanup_stale.py sweeps leftovers).
    def _cancel(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _cancel)
    signal.signal(signal.SIGINT, _cancel)

    session = boto3.Session(region_name=args.region)
    opts = Config(retries={"max_attempts": args.boto_max_attempts}, connect_timeout=10, read_timeout=60)
    vm = session.client("lambda-microvms", config=opts)
    # Regional endpoint + SigV4 presign (see K-333: global endpoint 307 + SigV2
    # header tokens break generic HTTP clients inside the VM).
    s3 = session.client(
        "s3",
        config=Config(
            retries={"max_attempts": 4}, connect_timeout=10, read_timeout=60,
            signature_version="s3v4", s3={"addressing_style": "virtual"},
        ),
        endpoint_url=f"https://s3.{args.region}.amazonaws.com",
    )

    # 1+2: package + upload + presign
    t0 = time.monotonic()
    if args.source_tarball:
        payload, sha = package_tarball(args.source_tarball, args.strip_components)
    else:
        payload, sha = package_source_dir(args.source_dir)
    prefix = f"{args.key_prefix.strip('/')}/{job_id}"
    artifact_key = f"{prefix}/artifact.tar.gz"
    result_key = f"{prefix}/result.bundle.tar.gz"
    s3.put_object(Bucket=args.bucket, Key=artifact_key, Body=payload)
    get_url = s3.generate_presigned_url(
        "get_object", Params={"Bucket": args.bucket, "Key": artifact_key}, ExpiresIn=900
    )
    put_url = s3.generate_presigned_url(
        "put_object", Params={"Bucket": args.bucket, "Key": result_key}, ExpiresIn=900
    )
    timings["package_upload_s"] = round(time.monotonic() - t0, 3)

    microvm_id = args.vm_id
    created = False
    metadata = dict(kv.split("=", 1) for kv in args.label)
    summary: dict = {
        "jobId": job_id,
        "sha256": sha,
        "artifactBytes": len(payload),
        "artifactKey": artifact_key,
        "metadata": metadata,
    }
    result: dict | None = None
    try:
        # 3: launch VM unless reusing
        if microvm_id is None:
            t0 = time.monotonic()
            run_req = {
                "imageIdentifier": args.image_identifier,
                "ingressNetworkConnectors": [connector(args.region, "HTTP_INGRESS")],
                "egressNetworkConnectors": [connector(args.region, "INTERNET_EGRESS")],
                "maximumDurationInSeconds": args.max_duration_seconds,
                "idlePolicy": {
                    "autoResumeEnabled": True,
                    "maxIdleDurationSeconds": 600,
                    "suspendedDurationSeconds": 300,
                },
                # deterministic per job_id: boto3-level retries are idempotent
                "clientToken": hashlib.sha256(job_id.encode()).hexdigest()[:32],
            }
            if args.image_version:
                run_req["imageVersion"] = args.image_version
            resp, attempts_log = run_microvm_with_retry(vm, run_req, attempts=args.run_attempts)
            summary["runMicrovmAttempts"] = attempts_log
            microvm_id = resp["microvmId"]
            created = True
            item = wait_running(vm, microvm_id, timeout=300)
            timings["vm_launch_s"] = round(time.monotonic() - t0, 3)
        else:
            item = vm.get_microvm(microvmIdentifier=microvm_id)
            if item["state"] != "RUNNING":
                raise RuntimeError(f"VM {microvm_id} is {item['state']}")
        endpoint = f"https://{item['endpoint']}"
        summary["microvmId"] = microvm_id

        # 4: auth token + submit job
        t0 = time.monotonic()
        token = vm.create_microvm_auth_token(
            microvmIdentifier=microvm_id,
            expirationInMinutes=args.token_minutes,
            allowedPorts=[{"port": 8080}],
        )["authToken"]["X-aws-proxy-auth"]
        spec = {
            "jobId": job_id,
            "artifact": {"url": get_url, "sha256": args.artifact_sha256 or sha},
            "result": {"url": put_url},
            "run": {
                "steps": args.step,
                "timeoutSeconds": args.job_timeout_seconds,
                "env": {},
            },
        }
        request_json("POST", f"{endpoint}/job", token, spec)
        timings["submit_s"] = round(time.monotonic() - t0, 3)

        # 5: poll status
        t0 = time.monotonic()
        deadline = time.monotonic() + args.job_timeout_seconds + 120
        status = "running"
        while time.monotonic() < deadline:
            s = request_json("GET", f"{endpoint}/job/status", token)
            status = s["status"]
            if status in ("succeeded", "failed", "error"):
                break
            time.sleep(3)
        timings["job_s"] = round(time.monotonic() - t0, 3)

        # 6: fetch result + logs, verify S3 bundle
        t0 = time.monotonic()
        result = request_json("GET", f"{endpoint}/job/result", token)
        (out_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True))
        try:
            logs = request_json("GET", f"{endpoint}/job/logs", token, raw=True)
            (out_dir / "logs.txt").write_bytes(logs)
        except Exception as exc:  # noqa: BLE001
            (out_dir / "logs.fetch-error.txt").write_text(str(exc))
        try:
            head = s3.head_object(Bucket=args.bucket, Key=result_key)
            summary["resultBundle"] = {"key": result_key, "bytes": head["ContentLength"]}
        except Exception as exc:  # noqa: BLE001
            summary["resultBundle"] = {"key": result_key, "error": str(exc)}
        timings["fetch_s"] = round(time.monotonic() - t0, 3)
        summary["jobStatus"] = status
    finally:
        # 7: always terminate VMs we created
        if created and microvm_id:
            t0 = time.monotonic()
            try:
                vm.terminate_microvm(microvmIdentifier=microvm_id)
            except Exception as exc:  # noqa: BLE001
                summary["terminateError"] = str(exc)
            summary["terminatedAs"] = wait_terminated(vm, microvm_id)
            timings["terminate_s"] = round(time.monotonic() - t0, 3)

    timings["total_s"] = round(time.monotonic() - t_all, 3)
    summary["timings"] = timings
    summary["outDir"] = str(out_dir)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    write_check_summary(out_dir, summary, result)
    print(json.dumps(summary, indent=2, sort_keys=True))

    if summary.get("jobStatus") == "succeeded":
        return 0
    if summary.get("jobStatus") in ("failed", "error"):
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
