"""Disposable-CI job agent for Lambda MicroVMs (runs inside the VM, port 8080).

The MicroVM image is fixed and shared. What changes per CI run is the *job
payload* delivered over authenticated HTTP ingress:

    POST /job {
      "jobId": "...",
      "artifact": {"url": "<presigned GET>", "sha256": "<hex>"},
      "result":  {"url": "<presigned PUT>"},            # optional
      "run": {"steps": ["python3 -m unittest discover -s tests -v"],
              "timeoutSeconds": 600, "env": {}}
    }

The agent downloads the artifact tarball, verifies SHA-256, extracts it into an
empty workspace, runs the steps (pipeline-owner supplied, executed via sh -c),
captures logs, uploads an optional result bundle, and exposes the outcome via
/job/status and /job/result. All evidence lives in this process; the VM is
terminated by the orchestrator afterwards.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

PORT = int(os.environ.get("PORT", "8080"))
JOB_ROOT = Path(os.environ.get("CI_JOB_ROOT", "/workspace/ci-jobs"))
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
HOOK_PREFIX = "/aws/lambda-microvms/runtime/v1/"
HOOKS = {"ready", "validate", "run", "resume", "suspend", "terminate"}

_state_lock = threading.RLock()
_state = {
    "status": "idle",  # idle | running | succeeded | failed | error
    "jobId": None,
    "error": None,
    "result": None,
    "microvmId": None,
    "hooks": [],
    "runHookPayload": None,
}
_log_lines: list[str] = []


def _log(msg: str, **fields) -> None:
    line = json.dumps({"t": round(time.time(), 3), "msg": msg, **fields})
    with _state_lock:
        _log_lines.append(line)
    print(line, flush=True)


def _json(handler, status: int, payload) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _text(handler, status: int, body: str) -> None:
    data = body.encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _download(url: str, expected_sha256: str, dest: Path) -> dict:
    """Stream-download the artifact, verifying SHA-256 as we go."""
    digest = hashlib.sha256()
    total = 0
    req = Request(url, headers={"User-Agent": "microvm-ci-agent/0.1"})
    with urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                raise ValueError(f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
            digest.update(chunk)
            out.write(chunk)
    actual = digest.hexdigest()
    return {"bytes": total, "sha256": actual, "sha256Match": actual == expected_sha256.lower()}


def _safe_extract(tar_path: Path, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            target = (dest / name).resolve()
            if not str(target).startswith(str(dest.resolve()) + os.sep):
                raise ValueError(f"unsafe member path in artifact: {name}")
            if member.isdev() or member.islnk() or member.issym():
                raise ValueError(f"refusing special member in artifact: {name}")
        tar.extractall(dest)
        count = len(tar.getmembers())
    return count


def _run_steps(steps: list[str], cwd: Path, env: dict, timeout: float, log_path: Path) -> list[dict]:
    safe_env = {k: os.environ.get(k, "") for k in ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR")}
    safe_env.update(env)
    results = []
    deadline = time.monotonic() + timeout
    with open(log_path, "wb") as logf:
        for step in steps:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                results.append({"step": step, "exitCode": None, "timedOut": True, "durationMs": 0})
                break
            started = time.monotonic()
            header = f"\n===== $ {step}\n".encode()
            logf.write(header)
            logf.flush()
            timed_out = False
            try:
                proc = subprocess.run(
                    ["sh", "-c", step],
                    cwd=str(cwd),
                    env=safe_env,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    timeout=remaining,
                )
                code = proc.returncode
            except subprocess.TimeoutExpired:
                code = None
                timed_out = True
            duration_ms = int((time.monotonic() - started) * 1000)
            results.append(
                {"step": step, "exitCode": code, "timedOut": timed_out, "durationMs": duration_ms}
            )
            if code != 0:
                break
    return results


def _upload_bundle(result_url: str, bundle: bytes) -> dict:
    req = Request(result_url, data=bundle, method="PUT",
                  headers={"Content-Type": "application/gzip"})
    with urlopen(req, timeout=60) as resp:
        return {"status": resp.status}


def _build_bundle(job_dir: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("result.json", "logs.txt"):
            p = job_dir / name
            if p.exists():
                tar.add(p, arcname=name)
    return buf.getvalue()


def _execute_job(spec: dict) -> None:
    job_id = spec["jobId"]
    job_dir = JOB_ROOT / job_id
    src_dir = job_dir / "src"
    job_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    result = {
        "jobId": job_id,
        "status": "error",
        "startedAt": started,
        "phases": {},
    }
    try:
        artifact = spec["artifact"]
        tgz = job_dir / "artifact.tar.gz"
        t0 = time.monotonic()
        dl = _download(artifact["url"], artifact["sha256"], tgz)
        result["phases"]["download"] = {"ms": int((time.monotonic() - t0) * 1000), **dl}
        if not dl["sha256Match"]:
            result["status"] = "failed"
            result["error"] = "artifact sha256 mismatch"
            raise SystemExit
        t0 = time.monotonic()
        members = _safe_extract(tgz, src_dir)
        result["phases"]["extract"] = {"ms": int((time.monotonic() - t0) * 1000), "files": members}

        run = spec.get("run", {})
        steps = run.get("steps") or []
        if not isinstance(steps, list) or not all(isinstance(s, str) for s in steps):
            raise ValueError("run.steps must be a list of strings")
        t0 = time.monotonic()
        step_results = _run_steps(
            steps, src_dir, run.get("env") or {},
            float(run.get("timeoutSeconds", 600)), job_dir / "logs.txt",
        )
        result["phases"]["run"] = {"ms": int((time.monotonic() - t0) * 1000)}
        result["steps"] = step_results
        result["status"] = (
            "succeeded" if all(s["exitCode"] == 0 for s in step_results) else "failed"
        )
        if not step_results:
            result["status"] = "failed"
            result["error"] = "no steps executed"
    except SystemExit:
        pass
    except Exception as exc:  # noqa: BLE001 - the agent is the error boundary
        result["status"] = "error"
        result["error"] = f"{exc.__class__.__name__}: {exc}"
        _log("job-error", error=result["error"], trace=traceback.format_exc()[-2000:])
    result["endedAt"] = time.time()
    result["durationMs"] = int((result["endedAt"] - started) * 1000)
    (job_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True))

    result_url = (spec.get("result") or {}).get("url")
    if result_url:
        try:
            up = _upload_bundle(result_url, _build_bundle(job_dir))
            result["resultUpload"] = up
            (job_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True))
        except Exception as exc:  # noqa: BLE001
            result["resultUpload"] = {"error": f"{exc.__class__.__name__}: {exc}"}
    with _state_lock:
        _state["status"] = result["status"]
        _state["result"] = result
    _log("job-finished", status=result["status"], durationMs=result["durationMs"])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet default access log
        _log("http", line=fmt % args)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            with _state_lock:
                snap = {"status": "ok", "jobStatus": _state["status"], "jobId": _state["jobId"]}
            return _json(self, 200, snap)
        if self.path == "/job/status":
            with _state_lock:
                snap = {k: _state[k] for k in ("status", "jobId", "error")}
            return _json(self, 200, snap)
        if self.path == "/job/result":
            with _state_lock:
                if _state["result"] is None:
                    return _json(self, 404, {"error": "no result"})
                return _json(self, 200, _state["result"])
        if self.path == "/job/logs":
            job_dir = JOB_ROOT / str(_state.get("jobId") or "")
            log = job_dir / "logs.txt"
            if log.is_file():
                return _text(self, 200, log.read_text(errors="replace"))
            with _state_lock:
                return _text(self, 200, "\n".join(_log_lines))
        return _json(self, 404, {"error": "not found", "path": self.path})

    def do_POST(self):  # noqa: N802
        if self.path.startswith(HOOK_PREFIX) and self.path[len(HOOK_PREFIX):] in HOOKS:
            hook = self.path[len(HOOK_PREFIX):]
            length = int(self.headers.get("Content-Length") or 0)
            payload = {}
            if length:
                try:
                    payload = json.loads(self.rfile.read(min(length, 65536)))
                except ValueError:
                    payload = {}
            with _state_lock:
                _state["hooks"].append(hook)
                if hook == "run":
                    _state["microvmId"] = payload.get("microvmId")
                    _state["runHookPayload"] = payload.get("runHookPayload")
            return _json(self, 200, {"status": "ok", "hook": hook})
        if self.path == "/job":
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= 1024 * 1024:
                return _json(self, 400, {"error": "missing or oversized job spec"})
            try:
                spec = json.loads(self.rfile.read(length))
                assert spec["jobId"] and spec["artifact"]["url"] and spec["artifact"]["sha256"]
            except (ValueError, KeyError, AssertionError) as exc:
                return _json(self, 400, {"error": f"invalid job spec: {exc}"})
            with _state_lock:
                if _state["status"] == "running":
                    return _json(self, 409, {"error": "job already running", "jobId": _state["jobId"]})
                _state["status"] = "running"
                _state["jobId"] = spec["jobId"]
                _state["result"] = None
                _state["error"] = None
            threading.Thread(target=_execute_job, args=(spec,), daemon=True).start()
            return _json(self, 202, {"jobId": spec["jobId"], "status": "accepted"})
        return _json(self, 404, {"error": "not found", "path": self.path})


def main() -> None:
    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    _log("ci-agent-listening", port=PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
