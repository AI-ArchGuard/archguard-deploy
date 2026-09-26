#!/usr/bin/env python3
"""Run a pinned Scanner in CI, submit its report, and publish the final gate."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid


class GateFailure(Exception):
    def __init__(self, message, exit_code):
        super().__init__(message)
        self.exit_code = exit_code


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise GateFailure(f"Missing required configuration: {name}", 64)
    return value


def request_json(url, method, token, value=None, extra_headers=None):
    data = None if value is None else json.dumps(value, separators=(",", ":")).encode()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    headers.update(extra_headers or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, headers, method), timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, ValueError) as error:
        raise GateFailure(f"API request failed: {type(error).__name__}", 70) from error


def retry_post_json(request, timeout, operation):
    """Retry only temporary transport failures; callers must tolerate repeated POSTs."""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                raise GateFailure(f"{operation} failed: HTTP {error.code}", 70) from error
            error.close()
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 2:
                raise GateFailure(f"{operation} failed: {type(error).__name__}", 70) from error
        except ValueError as error:
            raise GateFailure(f"{operation} failed: invalid JSON response", 70) from error
        time.sleep(2 ** attempt)


def publish_status(url, token, value):
    data = json.dumps(value, separators=(",", ":")).encode()
    request = urllib.request.Request(url, data, {
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"}, "POST")
    return retry_post_json(request, 30, "GitHub status publication")


def multipart(metadata, report):
    boundary = f"archguard-{uuid.uuid4().hex}"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"metadata\"\r\n"
            "Content-Type: application/json\r\n\r\n").encode()
    body += json.dumps(metadata, separators=(",", ":")).encode() + b"\r\n"
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"report\"; filename=\"report.json\"\r\n"
             "Content-Type: application/json\r\n\r\n").encode()
    body += report + f"\r\n--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", body


def submit(url, token, key, metadata, report):
    content_type, body = multipart(metadata, report)
    request = urllib.request.Request(url, body, {
        "Authorization": f"Bearer {token}", "Idempotency-Key": key,
        "Content-Type": content_type, "Accept": "application/json"}, "POST")
    return retry_post_json(request, 60, "Report submission")


def await_gate(url, token, submission_id):
    for attempt in range(5):
        gate = request_json(url, "GET", token)
        if gate.get("submissionId") == submission_id:
            return gate
        if attempt < 4:
            time.sleep(2)
    raise GateFailure("Platform gate did not complete", 70)


def await_current_head(url, token, sha, gate_id):
    for attempt in range(5):
        try:
            current = request_json(url, "GET", token)
        except GateFailure:
            if attempt == 4:
                raise
            time.sleep(2)
            continue
        if current.get("headSha") == sha and current.get("currentGateEvaluationId") == gate_id:
            return
        if current.get("headSha") not in (None, sha):
            raise GateFailure("PR head moved; stale result was not published", 70)
        if attempt < 4:
            time.sleep(2)
    raise GateFailure("Signed PR webhook has not associated this gate", 70)


def revision_from_event(event_name, event, repository_id, sha, ref_name):
    pr = event.get("pull_request") if event_name == "pull_request" else None
    if pr:
        head = pr["head"]["sha"]
        revision = {"provider": "github", "providerRepositoryId": repository_id,
                    "commitSha": head, "targetBranch": pr["base"]["ref"]}
        reference = {"externalId": str(pr["number"]), "headSha": head,
                     "baseSha": pr["base"]["sha"]}
    else:
        revision = {"provider": "github", "providerRepositoryId": repository_id,
                    "commitSha": sha, "targetBranch": ref_name}
        reference = None
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision["commitSha"]):
        raise GateFailure("Git commit SHA is invalid", 64)
    return revision, reference


def require_checkout_revision(workspace, sha):
    actual = subprocess.run(["git", "-C", str(workspace), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    if actual != sha:
        raise GateFailure("Checkout is not the claimed Git commit", 64)


def run():
    platform = required("ARCHGUARD_PLATFORM_URL").rstrip("/")
    if not platform.startswith("https://") and not platform.startswith("http://127.0.0.1:"):
        raise GateFailure("Platform URL must use HTTPS outside localhost", 64)
    project_id, repository_id = required("ARCHGUARD_PROJECT_ID"), required("ARCHGUARD_REPOSITORY_ID")
    rule_set_id = required("ARCHGUARD_RULESET_VERSION_ID")
    scanner, rules = Path(required("ARCHGUARD_SCANNER_JAR")), Path(required("ARCHGUARD_RULES_FILE"))
    workspace = Path(required("GITHUB_WORKSPACE"))
    token, github_token = required("ARCHGUARD_CI_TOKEN"), required("GITHUB_TOKEN")
    event_name, github_repository = required("GITHUB_EVENT_NAME"), required("GITHUB_REPOSITORY")
    event = json.loads(Path(required("GITHUB_EVENT_PATH")).read_text(encoding="utf-8"))
    revision, pr = revision_from_event(event_name, event, required("GITHUB_REPOSITORY_ID"),
                                       required("GITHUB_SHA"), required("GITHUB_REF_NAME"))
    if not scanner.is_file() or not rules.is_file() or not workspace.is_dir():
        raise GateFailure("Scanner, rules, or checkout is missing", 64)
    require_checkout_revision(workspace, revision["commitSha"])
    report_file = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "archguard-governance-report.json"
    report_file.unlink(missing_ok=True)
    scan = subprocess.run(["java", "-jar", str(scanner), "scan", str(workspace),
                           "--rules", str(rules), "--output", str(report_file)], check=False)
    if scan.returncode not in (0, 2):
        raise GateFailure("Scanner failed before producing a valid governance report",
                          64 if scan.returncode == 64 else 70)
    if not report_file.is_file():
        raise GateFailure("Scanner did not write a report", 70)
    report = report_file.read_bytes()
    if len(report) > 50 * 1024 * 1024:
        raise GateFailure("Scanner report exceeds 50 MiB", 70)
    metadata = {"ruleSetVersionId": rule_set_id, "revision": revision, "pullRequest": pr,
                "scannerVersion": "0.2.1", "schemaVersion": "0.1.0",
                "reportSha256": hashlib.sha256(report).hexdigest()}
    base = f"{platform}/api/v1/projects/{project_id}/repositories/{repository_id}"
    key = hashlib.sha256((str(uuid.UUID(project_id)) + ":" + str(uuid.UUID(repository_id)) + ":" +
                          revision["commitSha"] + ":" + rule_set_id + ":" + metadata["reportSha256"])
                         .encode()).hexdigest()
    submission = submit(f"{base}/report-submissions", token, key, metadata, report)
    submission_id = submission["id"]
    gate = await_gate(f"{base}/report-submissions/{submission_id}/gate-evaluation", token, submission_id)
    if gate.get("submissionId") != submission_id or gate.get("revision", {}).get("commitSha") != revision["commitSha"]:
        raise GateFailure("Platform returned an unrelated gate", 70)
    exit_code = gate.get("ciExitCode")
    if exit_code not in (0, 2, 64, 70):
        raise GateFailure("Platform returned an invalid gate exit code", 70)
    if pr:
        await_current_head(f"{base}/github/pull-requests/{pr['externalId']}", token,
                           revision["commitSha"], gate.get("id"))
    state = {0: "success", 2: "failure", 64: "error", 70: "error"}[exit_code]
    description = f"ArchGuard governance: {gate['outcome']}"
    github_url = f"https://api.github.com/repos/{github_repository}/statuses/{revision['commitSha']}"
    publish_status(github_url, github_token,
                   {"state": state, "context": "archguard/governance", "description": description})
    print(f"Governance gate: {gate['outcome']} (exit {exit_code})")
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(run())
    except GateFailure as error:
        print(str(error), file=sys.stderr)
        sys.exit(error.exit_code)
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Invalid CI event or execution environment: {type(error).__name__}", file=sys.stderr)
        sys.exit(64)
