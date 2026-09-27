#!/usr/bin/env python3
"""Exercise the Stage 3 governance journey against a running local Compose stack.

Only synthetic Samples are scanned. A temporary Keycloak direct-grant client is
created in the local realm for the test and removed even when an assertion fails.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://127.0.0.1:8080"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def request(url: str, method: str = "GET", *, token: str | None = None,
            payload: object | None = None, content_type: str | None = None,
            headers: dict[str, str] | None = None,
            expected: tuple[int, ...] = (200,)) -> tuple[int, dict, dict]:
    if payload is None:
        data = None
    elif isinstance(payload, bytes):
        data = payload
    elif content_type == "application/x-www-form-urlencoded":
        data = urllib.parse.urlencode(payload).encode()
    else:
        data = json.dumps(payload, separators=(",", ":")).encode()
        content_type = "application/json"
    all_headers = dict(headers or {})
    if token:
        all_headers["Authorization"] = f"Bearer {token}"
    if content_type:
        all_headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data, all_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            status, raw, response_headers = response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        status, raw, response_headers = error.code, error.read(), dict(error.headers)
    try:
        value = json.loads(raw) if raw else {}
    except ValueError:
        value = {}
    if status not in expected:
        code = value.get("code", "unexpected_response")
        raise AssertionError(f"{method} {urllib.parse.urlparse(url).path}: HTTP {status} ({code})")
    return status, value, response_headers


def local_credentials() -> tuple[dict[str, str], dict]:
    runtime = {}
    for line in (ROOT / ".local/runtime.env").read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        runtime[key] = value
    realm = json.loads((ROOT / ".local/keycloak/realm.json").read_text(encoding="utf-8"))
    return runtime, realm


def temporary_client(base_url: str, runtime: dict[str, str], realm: dict) -> tuple[str, str, str]:
    _, admin, _ = request(
        f"{base_url}/auth/realms/master/protocol/openid-connect/token", "POST",
        payload={"client_id": "admin-cli", "username": "admin",
                 "password": runtime["ARCHGUARD_LOCAL_KEYCLOAK_ADMIN_PASSWORD"],
                 "grant_type": "password"}, content_type="application/x-www-form-urlencoded")
    admin_token = admin["access_token"]
    template = next(client for client in realm["clients"] if client["clientId"] == "archguard-web")
    client_id = "archguard-acceptance-" + uuid.uuid4().hex[:12]
    _, _, response_headers = request(
        f"{base_url}/auth/admin/realms/archguard/clients", "POST", token=admin_token,
        payload={"clientId": client_id, "name": "Temporary local governance acceptance",
                 "enabled": True, "publicClient": True, "directAccessGrantsEnabled": True,
                 "standardFlowEnabled": False,
                 "defaultClientScopes": template["defaultClientScopes"],
                 "protocolMappers": template["protocolMappers"]}, expected=(201,))
    client_uuid = response_headers["Location"].rsplit("/", 1)[-1]
    password = next(user for user in realm["users"] if user["username"] == "maintainer")["credentials"][0]["value"]
    try:
        _, user, _ = request(
            f"{base_url}/auth/realms/archguard/protocol/openid-connect/token", "POST",
            payload={"client_id": client_id, "username": "maintainer",
                     "password": password, "grant_type": "password"},
            content_type="application/x-www-form-urlencoded")
    except BaseException:
        request(f"{base_url}/auth/admin/realms/archguard/clients/{client_uuid}",
                "DELETE", token=admin_token, expected=(204,))
        raise
    return admin_token, client_uuid, user["access_token"]


def multipart(metadata: dict, report: bytes) -> tuple[str, bytes]:
    boundary = "archguard-acceptance-" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"metadata\"\r\n"
            "Content-Type: application/json\r\n\r\n").encode()
    body += json.dumps(metadata, separators=(",", ":")).encode() + b"\r\n"
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"report\"; "
             "filename=\"report.json\"\r\nContent-Type: application/json\r\n\r\n").encode()
    body += report + f"\r\n--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", body


def scan(scanner: Path, source: Path, rules: Path, output: Path, expected_code: int) -> bytes:
    result = subprocess.run(["java", "-jar", str(scanner), "scan", str(source),
                             "--rules", str(rules), "--output", str(output)],
                            capture_output=True, text=True, check=False)
    require(result.returncode == expected_code,
            f"Scanner {source.name} exit {result.returncode}, expected {expected_code}")
    report = output.read_bytes()
    require(json.loads(report)["schemaVersion"] == "0.1.0", "Scanner schema changed")
    return report


def submit(base: str, token: str, rules_id: str, provider_id: str,
           commit: str, report: bytes, key: str, pr: str | None = None) -> tuple[int, dict]:
    metadata = {"ruleSetVersionId": rules_id,
                "revision": {"provider": "github", "providerRepositoryId": provider_id,
                             "commitSha": commit, "targetBranch": "main"},
                "pullRequest": ({"externalId": pr, "headSha": commit, "baseSha": "a" * 40}
                                if pr else None),
                "scannerVersion": "0.2.1", "schemaVersion": "0.1.0",
                "reportSha256": hashlib.sha256(report).hexdigest()}
    content_type, body = multipart(metadata, report)
    status, value, _ = request(base + "/report-submissions", "POST", token=token,
                               payload=body, content_type=content_type,
                               headers={"Idempotency-Key": key}, expected=(200, 202))
    return status, value


def webhook(base_url: str, secret: str, provider_id: str, head: str, at: datetime,
            expected: tuple[int, ...] = (200,), bad_signature: bool = False) -> dict:
    body = json.dumps({"action": "synchronize", "number": 7,
                       "repository": {"id": int(provider_id)},
                       "pull_request": {"updated_at": at.isoformat().replace("+00:00", "Z"),
                                        "head": {"sha": head},
                                        "base": {"sha": "a" * 40, "ref": "main"}}},
                      separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if bad_signature:
        signature = "0" * 64
    _, value, _ = request(base_url + "/api/v1/github/webhooks", "POST", payload=body,
                          content_type="application/json",
                          headers={"X-GitHub-Delivery": str(uuid.uuid4()),
                                   "X-GitHub-Event": "pull_request",
                                   "X-Hub-Signature-256": "sha256=" + signature}, expected=expected)
    return value


def run(base_url: str, scanner: Path, samples: Path) -> None:
    require(scanner.is_file(), "Pinned Scanner JAR is missing")
    fixture = samples / "governance/java-ci-journey"
    require((fixture / "baseline/archguard-rules.yaml").is_file(), "Fixed synthetic journey is missing")
    runtime, realm = local_credentials()
    request(base_url + "/", expected=(200,))
    admin_token, client_uuid, token = temporary_client(base_url, runtime, realm)
    try:
        suffix = uuid.uuid4().hex[:12]
        _, project, _ = request(base_url + "/api/v1/projects", "POST", token=token,
                                payload={"key": "g3h-" + suffix, "name": "Governance acceptance"},
                                expected=(201,))
        project_id = project["id"]
        project_url = f"{base_url}/api/v1/projects/{project_id}"
        _, repository, _ = request(project_url + "/repositories", "POST", token=token,
                                   payload={"key": "ci-journey", "name": "Synthetic CI journey",
                                            "mountPath": "governance/java-ci-journey/baseline"},
                                   expected=(201,))
        repository_id = repository["id"]
        base = project_url + f"/repositories/{repository_id}"
        identity = repository["scannerIdentity"]
        rules_text = (fixture / "baseline/archguard-rules.yaml").read_text(encoding="utf-8")
        rules_text = rules_text.replace("samples:java-ci-journey", identity)
        local = ROOT / ".local/acceptance"
        local.mkdir(parents=True, exist_ok=True)
        rules_file = local / "rules.yaml"
        rules_file.write_text(rules_text, encoding="utf-8", newline="\n")
        _, rules, _ = request(base + "/rule-sets", "POST", token=token,
                              payload={"key": "governance", "name": "Governance acceptance"},
                              expected=(201,))
        _, version, _ = request(base + f"/rule-sets/{rules['id']}/versions", "POST", token=token,
                                payload={"yaml": rules_text}, expected=(201,))
        version_id = version["id"]
        provider_id = str(100000000 + int(suffix[:8], 16) % 800000000)
        request(base + "/github/link", "PUT", token=token,
                payload={"providerRepositoryId": provider_id,
                         "ownerName": "AI-ArchGuard", "repositoryName": "synthetic-ci"})
        clean = scan(scanner, fixture / "baseline", rules_file, local / "baseline.json", 0)
        violation = scan(scanner, fixture / "introduced", rules_file, local / "introduced.json", 2)
        require(len(json.loads(clean)["findings"]) == 0, "Baseline is not clean")
        require(len(json.loads(violation)["findings"]) == 1, "Expected one introduced Finding")

        baseline_status, baseline_submission = submit(base, token, version_id, provider_id,
                                                      "a" * 40, clean, "baseline-" + suffix)
        require(baseline_status == 202, "Baseline report was not accepted")
        _, initial_gate, _ = request(base + f"/report-submissions/{baseline_submission['id']}/gate-evaluation",
                                     token=token)
        require((initial_gate["outcome"], initial_gate["ciExitCode"]) == ("ERROR", 64),
                "Missing baseline did not fail closed")
        _, initial_evaluation, _ = request(base + f"/gate-evaluations/{initial_gate['id']}", token=token)
        _, baseline, _ = request(base + "/baselines", "POST", token=token,
                                 payload={"targetBranch": "main", "ruleSetVersionId": version_id,
                                          "scanJobId": initial_evaluation["candidateJobId"],
                                          "commitSha": "a" * 40}, expected=(201,))
        require(baseline["version"] == 1, "Initial baseline version is wrong")

        first_at = datetime.now(timezone.utc) - timedelta(seconds=2)
        require(webhook(base_url, runtime["ARCHGUARD_GITHUB_WEBHOOK_SECRET"], provider_id,
                        "b" * 40, first_at)["disposition"] == "APPLIED", "PR webhook was not applied")
        webhook(base_url, runtime["ARCHGUARD_GITHUB_WEBHOOK_SECRET"], provider_id,
                "b" * 40, first_at, expected=(401,), bad_signature=True)
        failed_status, failed_submission = submit(base, token, version_id, provider_id,
                                                  "b" * 40, violation, "introduced-" + suffix, "7")
        require(failed_status == 202, "Introduced report was not accepted")
        _, failed_gate, _ = request(base + f"/report-submissions/{failed_submission['id']}/gate-evaluation",
                                    token=token)
        require((failed_gate["outcome"], failed_gate["ciExitCode"], failed_gate["counts"]["NEW"])
                == ("FAIL", 2, 1), "Introduced high Finding did not fail the gate")
        _, failed_evaluation, _ = request(base + f"/gate-evaluations/{failed_gate['id']}", token=token)
        _, comparison, _ = request(base + f"/comparisons/{failed_evaluation['comparisonId']}", token=token)
        require(comparison["findings"][0]["classification"] == "NEW", "Finding is not NEW")
        replay_status, replay = submit(base, token, version_id, provider_id,
                                       "b" * 40, violation, "introduced-" + suffix, "7")
        require(replay_status == 200 and replay["id"] == failed_submission["id"],
                "Same report was not idempotent")

        now = datetime.now(timezone.utc)
        expiry = now + timedelta(seconds=8)
        _, exception, _ = request(base + "/policy-exceptions", "POST", token=token,
                                  payload={"targetBranch": "main", "ruleSetVersionId": version_id,
                                           "scopeType": "RULE",
                                           "scopeValue": "archguard.illegal-package-dependency",
                                           "reason": "Synthetic time-bound acceptance",
                                           "effectiveAt": (now - timedelta(seconds=1)).isoformat(),
                                           "expiresAt": expiry.isoformat()}, expected=(201,))
        _, excepted_gate, _ = request(base + "/gate-evaluations", "POST", token=token,
                                      payload={"targetBranch": "main", "ruleSetVersionId": version_id,
                                               "candidateJobId": failed_evaluation["candidateJobId"]},
                                      headers={"Idempotency-Key": "exception-valid-" + suffix}, expected=(201,))
        require((excepted_gate["outcome"], excepted_gate["ciExitCode"]) == ("PASS", 0),
                "Effective exception did not pass")
        require(exception["currentVersionId"] in excepted_gate["matchedExceptionVersionIds"],
                "Gate did not retain the matching exception version")
        time.sleep(max(0, (expiry - datetime.now(timezone.utc)).total_seconds()) + 1)
        _, expired_gate, _ = request(base + "/gate-evaluations", "POST", token=token,
                                     payload={"targetBranch": "main", "ruleSetVersionId": version_id,
                                              "candidateJobId": failed_evaluation["candidateJobId"]},
                                     headers={"Idempotency-Key": "exception-expired-" + suffix}, expected=(201,))
        require((expired_gate["outcome"], expired_gate["ciExitCode"]) == ("FAIL", 2),
                "Expired exception did not block again")

        second_at = datetime.now(timezone.utc)
        require(webhook(base_url, runtime["ARCHGUARD_GITHUB_WEBHOOK_SECRET"], provider_id,
                        "c" * 40, second_at)["disposition"] == "APPLIED", "Repair webhook was not applied")
        repaired_status, repaired_submission = submit(base, token, version_id, provider_id,
                                                      "c" * 40, clean, "repaired-" + suffix, "7")
        require(repaired_status == 202, "Repair report was not accepted")
        _, repaired_gate, _ = request(base + f"/report-submissions/{repaired_submission['id']}/gate-evaluation",
                                      token=token)
        require((repaired_gate["outcome"], repaired_gate["ciExitCode"]) == ("PASS", 0),
                "Repair did not pass the gate")
        _, current_pr, _ = request(base + "/github/pull-requests/7", token=token)
        require(current_pr["headSha"] == "c" * 40 and
                current_pr["currentGateEvaluationId"] == repaired_gate["id"],
                "Repaired PR is not the current authoritative head")
        _, repaired_evaluation, _ = request(base + f"/gate-evaluations/{repaired_gate['id']}", token=token)
        _, revision_delta, _ = request(base + "/github/pull-requests/7/revision-delta?"
                                       + urllib.parse.urlencode({"ruleSetVersionId": version_id}), token=token)
        result = {"projectId": project_id, "baselineVersionId": baseline["id"],
                  "newCount": failed_gate["counts"]["NEW"], "introducedExit": failed_gate["ciExitCode"],
                  "exceptionExit": excepted_gate["ciExitCode"],
                  "expiredExit": expired_gate["ciExitCode"],
                  "repairExit": repaired_gate["ciExitCode"],
                  "baselineResolvedCount": repaired_evaluation["resolvedCount"],
                  "prRevisionResolvedCount": revision_delta["resolvedCount"]}
        print(json.dumps(result, sort_keys=True))
        require(repaired_evaluation["resolvedCount"] == 0,
                "Baseline classification changed its reference point")
        require(revision_delta["reference"] == "PR_PREVIOUS_REVISION"
                and revision_delta["availability"] == "AVAILABLE"
                and revision_delta["previousHeadSha"] == "b" * 40
                and revision_delta["currentHeadSha"] == "c" * 40
                and revision_delta["resolvedCount"] == 1
                and revision_delta["findings"][0]["classification"] == "RESOLVED",
                "PR revision delta did not classify the repair as RESOLVED")
    finally:
        request(f"{base_url}/auth/admin/realms/archguard/clients/{client_uuid}",
                "DELETE", token=admin_token, expected=(204,))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_URL)
    parser.add_argument("--scanner-jar", type=Path, default=ROOT / ".local/scanner.jar")
    parser.add_argument("--samples-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.base_url.rstrip("/"), args.scanner_jar, args.samples_root)
    except (AssertionError, KeyError, OSError, ValueError) as error:
        print(f"Compose governance acceptance failed: {error}", file=sys.stderr)
        sys.exit(1)
