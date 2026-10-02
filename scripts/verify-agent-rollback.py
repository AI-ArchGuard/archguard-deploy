#!/usr/bin/env python3
"""Read-only history verification for the named synthetic 4H rollback rehearsal.

This does not deploy, disable Flyway validation, restore/drop data or call a model.
The operator performs the documented shutdown, backup, rollback and restoration.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("governance", ROOT / "scripts/verify-governance-compose.py")
governance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(governance)

TABLES = {
    "public.flyway_schema_history": "installed_rank",
    "public.flyway_agent_schema_history": "installed_rank",
    "agent_document.upload_requests": "project_id, idempotency_key",
    "agent_document.documents": "id",
    "agent_document.document_versions": "id",
    "agent_document.document_fragments": "version_id, fragment_index",
    "agent.requests": "id",
    "agent.budget_usage": "scope, scope_id, utc_day",
    "audit.audit_records": "id",
}


def database_snapshot():
    queries = []
    for table, order in TABLES.items():
        where = " WHERE action LIKE 'agent.%'" if table == "audit.audit_records" else ""
        queries.append(f"SELECT '{table}', count(*), md5(COALESCE(string_agg(to_jsonb(t)::text, E'\\n' ORDER BY {order}), '')) FROM {table} t{where}")
    result = subprocess.run(["docker", "exec", "archguard-agent-4h-postgres-1", "psql", "-X", "-U", "archguard", "-d", "archguard",
                             "-v", "ON_ERROR_STOP=1", "-A", "-t", "-F", "|", "-c", ";".join(queries)],
                            capture_output=True, text=True, check=False)
    governance.require(result.returncode == 0, "Read-only database history snapshot failed")
    snapshot = {}
    for line in result.stdout.splitlines():
        table, count, digest = line.split("|")
        snapshot[table] = {"rows": int(count), "digest": digest}
    governance.require(set(snapshot) == set(TABLES), "Incomplete history snapshot")
    governance.require(snapshot["agent.requests"]["rows"] > 0 and snapshot["agent_document.document_versions"]["rows"] > 0,
                       "Rollback rehearsal needs existing Agent history")
    return snapshot


def assert_unchanged(before, after):
    governance.require(set(before) == set(TABLES) and set(after) == set(TABLES), "Incomplete history snapshot")
    for table in TABLES:
        governance.require(before[table] == after[table], f"Historical rows changed: {table}")


def verify_runner(context):
    """New deterministic work must still reach the isolated Scanner after rollback."""
    root, token = context["project_url"], context["token"]
    body = {"repositoryId": context["repository_id"], "ruleSetVersionId": context["rule_set_version_id"]}
    key = "rollback-runner-" + uuid.uuid4().hex
    created = governance.request(root + "/scan-jobs", "POST", token=token, payload=body,
                                 headers={"Idempotency-Key": key}, expected=(201, 202))[1]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = governance.request(root + "/scan-jobs/" + created["id"], token=token)[1]
        if job["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(0.5)
    governance.require(job["status"] == "SUCCEEDED" and job["outcome"] == "PASS", "Rollback Scanner Runner did not pass clean input")
    governance.require(governance.request(root + "/scan-jobs/" + created["id"] + "/findings", token=token)[1] == [],
                       "Clean rollback scan gained Findings")
    replay = governance.request(root + "/scan-jobs", "POST", token=token, payload=body,
                                headers={"Idempotency-Key": key}, expected=(200, 201, 202))[1]
    governance.require(replay["id"] == created["id"], "Rollback scan replay was not idempotent")
    print(json.dumps({"runnerVerified": True, "scanJobId": created["id"], "outcome": job["outcome"]}, sort_keys=True))


def capture_api(base_url, fixture, token, restored):
    root = base_url + "/api/v1/projects/" + fixture["projectId"]
    job_url = root + "/scan-jobs/" + fixture["browserScanJobId"]
    job = governance.request(job_url, token=token)[1]
    findings = governance.request(job_url + "/findings", token=token)[1]
    repo = root + "/repositories/" + fixture["repositoryId"]
    pr = governance.request(repo + "/github/pull-requests/7", token=token)[1]
    gate = governance.request(repo + "/gate-evaluations/" + pr["currentGateEvaluationId"], token=token)[1]
    governance.require((gate["outcome"], gate["ciExitCode"]) == ("FAIL", 2), "Historical FAIL / CI 2 changed")
    if restored:
        explanation = governance.request(root + "/agent/requests/" + fixture["explanationId"], token=token)[1]
        summary = governance.request(root + "/agent/requests/" + fixture["summaryId"], token=token)[1]
        version = governance.request(root + "/documents/versions/" + fixture["documentVersionId"], token=token)[1]
        governance.require(explanation["state"] == summary["state"] == "SUCCEEDED", "Historical advice inaccessible")
        governance.require(any(c.get("documentVersionId") == version["id"] and c.get("contentSha256") == version["contentSha256"]
                               for c in explanation["result"]["citations"]), "Old document citation changed")
    else:
        for path in ("/agent/requests/" + fixture["explanationId"], "/documents/versions/" + fixture["documentVersionId"]):
            unavailable = governance.request(root + path, token=token, expected=(503,))[1]
            governance.require(unavailable.get("code") == "agent.unavailable" and unavailable.get("traceId"),
                               "Rollback proxy did not explicitly close Agent routes")
    # Stage 3 PR DTO lacks the additive Agent revision field; compare deterministic data only.
    return {"job": job, "findings": findings, "gate": gate,
            "pr": {key: pr[key] for key in ("externalId", "headSha", "targetBranch", "currentGateEvaluationId")}}


def run(args):
    runtime_root = args.runtime_root.resolve()
    governance.ROOT = runtime_root
    if args.samples_root:
        governance.require(args.phase == "old", "New-work rehearsal is only valid during old-app rollback")
        governance.run(args.base_url, runtime_root / ".local/scanner.jar", args.samples_root, verify_runner)
    fixture = json.loads((runtime_root / ".local/agent-acceptance-result.json").read_text(encoding="utf-8-sig"))
    governance.require(fixture["expected"] == "SUCCEEDED" and fixture["realModelCalls"] == 0, "Not a synthetic success fixture")
    runtime, realm = governance.local_credentials()
    _, client, token = governance.temporary_client(args.base_url, runtime, realm)
    try:
        api = capture_api(args.base_url, fixture, token, args.phase != "old")
    finally:
        governance.cleanup_client(args.base_url, runtime, client)
    current = database_snapshot()
    if args.phase == "capture":
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        args.snapshot.write_text(json.dumps({"database": current, "api": api}, sort_keys=True, indent=2), encoding="utf-8")
    else:
        before = json.loads(args.snapshot.read_text(encoding="utf-8"))
        assert_unchanged(before["database"], current)
        governance.require(before["api"] == api, "Deterministic API history changed")
    print(json.dumps({"phase": args.phase, "historicalTables": len(current), "historyUnchanged": args.phase != "capture",
                      "failExit": 2, "realModelCalls": 0, "browserVerified": False}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("capture", "old", "restored"))
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--base-url", choices=("http://127.0.0.1:8081",), default="http://127.0.0.1:8081")
    parser.add_argument("--snapshot", type=Path, default=ROOT / ".local/rollback-history.json")
    parser.add_argument("--samples-root", type=Path, help="Explicitly create synthetic governance/Runner work during old-app rehearsal")
    run(parser.parse_args())
