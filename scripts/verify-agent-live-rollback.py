#!/usr/bin/env python3
"""Fixed-target read-only final personal-live history capture/comparison.

No API calls, credential reads, deployment changes or model requests. The
operator completes shutdown first and supplies the actual candidate manifest.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIR = ROOT / ".local/agent-personal-live"
MANIFEST_FILE = PRIVATE_DIR / "candidate.json"
SNAPSHOT_FILE = PRIVATE_DIR / "rollback-history.json"
KIND = "PERSONAL_LIVE_FINAL_ROLLBACK"
SCHEMA_VERSION = "0.1.0"
MAX_AUDIT_ROWS = 5000
MAX_BYTES = 4 * 1024 * 1024
TABLES = {
    "public.flyway_schema_history": "installed_rank",
    "public.flyway_agent_schema_history": "installed_rank",
    "agent_document.upload_requests": "project_id,idempotency_key",
    "agent_document.documents": "id",
    "agent_document.document_versions": "id",
    "agent_document.document_fragments": "version_id,fragment_index",
    "agent.requests": "id",
    "agent.budget_usage": "scope,scope_id,utc_day",
    "agent.personal_enablements": "id",
    "agent.enablement_revocations": "enablement_id",
    "agent.project_settings": "project_id",
    "agent.live_batches": "id",
    "agent.live_batch_usage": "batch_id",
    "agent.live_batch_revocations": "batch_id",
    "agent.live_budget_usage": "scope,scope_id,utc_day",
    "agent.live_attempts": "request_id",
    "agent.live_outcomes": "request_id",
    "agent.live_request_links": "request_id",
    "agent.live_batch_stops": "batch_id",
    "agent.live_template_request_slots": "project_id,batch_id,template_id",
    "audit.audit_records": "id",
}
MAIN_SCRIPTS = (
    "V1__create_project_and_audit_schemas.sql", "V2__create_platform_mvp_schemas.sql",
    "V3__create_governance_baselines.sql", "V4__create_governance_policy_and_gates.sql",
    "V5__create_github_ci_governance.sql", "V6__audit_governance_write_failures.sql",
    "V7__create_github_pr_head_revisions.sql", "V8__create_agent_document_versions.sql",
)
AGENT_SCRIPTS = (
    "V9__create_agent_explanations.sql", "V10__enable_agent_pr_summaries.sql",
    "V11__personal_agent_enablements.sql", "V12__live_agent_accounting.sql",
    "V13__synthetic_batch_provenance.sql", "V14__live_request_links.sql",
    "V15__context_cost_policy.sql", "V16__context_template_request_slots.sql",
)
CANDIDATES = {
    "docs": "077a7c5afa12557543ee04e14321701c3537931a",
    "platform": "af821fc99553d462a2176cba5af70be7cc960c75",
    "web": "5c5a7a021210876cda55850d7898e11aa52781aa",
    "scanner": "d4b8e98bfdabbc78f65910ed37e3062167d04b07",
    "samples": "a53a5bbea2630aac2135aa217d961cdbb77851a3",
}
MIGRATION_FIELDS = {"version", "installed_rank", "type", "script", "checksum", "success", "digest"}
AUDIT_FIELDS = {"id", "action", "projectId", "traceId", "digest"}


def require(condition):
    if not condition:
        raise AssertionError("FINAL_HISTORY_UNAVAILABLE")


def exact(value, fields):
    require(isinstance(value, dict) and set(value) == set(fields))


def integer(value, maximum=9223372036854775807):
    require(type(value) is int and 0 <= value <= maximum)


def digest(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None)


def canonical_uuid(value):
    require(isinstance(value, str) and len(value) == 36)
    try:
        require(str(uuid.UUID(value)) == value)
    except ValueError:
        raise AssertionError("FINAL_HISTORY_UNAVAILABLE") from None


def short_ref(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is not None)
    require(not value.lower().startswith(("sk-", "ghp_", "github_pat_")))


def audit_record(row):
    exact(row, AUDIT_FIELDS)
    canonical_uuid(row["id"])
    if row["projectId"] is not None:
        canonical_uuid(row["projectId"])
    require(isinstance(row["action"], str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,79}", row["action"]) is not None)
    require(isinstance(row["traceId"], str) and re.fullmatch(r"[a-f0-9]{32}", row["traceId"]) is not None)
    digest(row["digest"])


def validate_migrations(main, agent):
    """Check Flyway metadata, never substitute a source SHA for its checksum."""
    for rows, scripts, start in ((main, MAIN_SCRIPTS, 1), (agent, AGENT_SCRIPTS, 9)):
        require(isinstance(rows, list) and len(rows) == len(scripts) + (start == 9))
        for index, row in enumerate(rows):
            exact(row, MIGRATION_FIELDS)
            require(type(row["installed_rank"]) is int and row["installed_rank"] == index + 1)
            require(row["success"] is True)
            digest(row["digest"])
            baseline = start == 9 and index == 0
            if baseline:
                require(row["version"] == "8" and row["type"] == "BASELINE")
                require(row["script"] == "<< Flyway Baseline >>" and row["checksum"] is None)
            else:
                offset = index - (start == 9)
                require(row["version"] == str(start + offset) and row["type"] == "SQL")
                require(row["script"] == scripts[offset])
                require(type(row["checksum"]) is int and -2147483648 <= row["checksum"] <= 2147483647)


def parse_database_snapshot(records):
    """Parse only fixed metadata records; no raw table/model/document/audit body."""
    require(isinstance(records, list) and len(records) <= MAX_AUDIT_ROWS + 40)
    tables, histories, audit, pending = {}, {"main": [], "agent": []}, {}, None
    for record in records:
        require(isinstance(record, dict))
        kind = record.get("kind")
        if kind == "table":
            exact(record, {"kind", "table", "rows", "digest"})
            table = record["table"]
            require(isinstance(table, str) and table in TABLES and table not in tables)
            integer(record["rows"])
            digest(record["digest"])
            tables[table] = {"rows": record["rows"], "digest": record["digest"]}
        elif kind == "migration":
            exact(record, MIGRATION_FIELDS | {"kind", "history"})
            require(isinstance(record["history"], str) and record["history"] in histories)
            histories[record["history"]].append({key: record[key] for key in MIGRATION_FIELDS})
        elif kind == "audit":
            exact(record, AUDIT_FIELDS | {"kind"})
            row = {key: record[key] for key in AUDIT_FIELDS}
            audit_record(row)
            require(row["id"] not in audit)
            audit[row["id"]] = row
        elif kind == "state":
            exact(record, {"kind", "queued", "running"})
            require(pending is None)
            integer(record["queued"])
            integer(record["running"])
            pending = record["queued"] + record["running"]
            require(pending == 0)
        else:
            require(False)
    require(set(tables) == set(TABLES) and pending == 0)
    require(tables["audit.audit_records"]["rows"] == len(audit) <= MAX_AUDIT_ROWS)
    validate_migrations(histories["main"], histories["agent"])
    require(tables["public.flyway_schema_history"]["rows"] == len(histories["main"]))
    require(tables["public.flyway_agent_schema_history"]["rows"] == len(histories["agent"]))
    return {"tables": tables, "migrations": histories, "audit": audit, "pendingRequests": pending}


def validate_database(value):
    exact(value, {"tables", "migrations", "audit", "pendingRequests"})
    require(isinstance(value["tables"], dict) and isinstance(value["audit"], dict))
    exact(value["migrations"], {"main", "agent"})
    require(type(value["pendingRequests"]) is int and value["pendingRequests"] == 0)
    records = []
    for table, row in value["tables"].items():
        exact(row, {"rows", "digest"})
        records.append({"kind": "table", "table": table, **row})
    for history, rows in value["migrations"].items():
        require(isinstance(rows, list))
        records.extend({"kind": "migration", "history": history, **row} for row in rows)
    for key, row in value["audit"].items():
        audit_record(row)
        require(key == row["id"])
        records.append({"kind": "audit", **row})
    records.append({"kind": "state", "queued": 0, "running": 0})
    parse_database_snapshot(records)


def approved_triples(values):
    require(isinstance(values, (tuple, list)) and len(values) <= MAX_AUDIT_ROWS)
    approved = set()
    for triple in values:
        require(isinstance(triple, (tuple, list)) and len(triple) == 3)
        action, project, trace = triple
        canonical_uuid(project)
        audit_record({"id": project, "action": action, "projectId": project, "traceId": trace, "digest": "0" * 64})
        require(not action.startswith(("agent.", "agent_document.", "AGENT_CREDENTIAL_")))
        approved.add((action, project, trace))
    return approved


def assert_unchanged(before, after, allowed_audit_appends=()):
    validate_database(before)
    validate_database(after)
    allowed = approved_triples(allowed_audit_appends)
    require(before["migrations"] == after["migrations"])
    for table in TABLES:
        if table != "audit.audit_records":
            require(before["tables"][table] == after["tables"][table])
    for identifier, row in before["audit"].items():
        require(after["audit"].get(identifier) == row)
    added = set(after["audit"]) - set(before["audit"])
    for identifier in added:
        row = after["audit"][identifier]
        require(not row["action"].startswith(("agent.", "agent_document.", "AGENT_CREDENTIAL_")))
        require((row["action"], row["projectId"], row["traceId"]) in allowed)
    if not added:
        require(before["tables"]["audit.audit_records"] == after["tables"]["audit.audit_records"])


def validate_manifest(value):
    fields = {"schemaVersion", "kind", "deploymentId", "candidates", "namespaceProofRef", "configProofRef", "shutdownComplete"}
    require(isinstance(value, dict))
    exact(value, fields | ({"allowedAuditAppends"} if "allowedAuditAppends" in value else set()))
    require(value["schemaVersion"] == SCHEMA_VERSION and value["kind"] == KIND and value["shutdownComplete"] is True)
    canonical_uuid(value["deploymentId"])
    short_ref(value["namespaceProofRef"])
    short_ref(value["configProofRef"])
    exact(value["candidates"], set(CANDIDATES) | {"deploy"})
    require(all(value["candidates"][name] == sha for name, sha in CANDIDATES.items()))
    sha = value["candidates"]["deploy"]
    require(isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{40}", sha) is not None and sha != "0" * 40)
    approved_triples(value.get("allowedAuditAppends", []))


def validate_snapshot(snapshot, candidate):
    exact(snapshot, {"schemaVersion", "kind", "manifest", "database"})
    validate_manifest(candidate)
    validate_manifest(snapshot["manifest"])
    require(snapshot["schemaVersion"] == SCHEMA_VERSION and snapshot["kind"] == KIND)
    require(snapshot["manifest"] == candidate)
    validate_database(snapshot["database"])


def row_digest():
    return "encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex')"


def snapshot_sql():
    queries = ["BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY",
               "SET LOCAL TIME ZONE 'UTC'", "SET LOCAL statement_timeout = '5s'", "SET LOCAL lock_timeout = '5s'"]
    for table, order in TABLES.items():
        queries.append("SELECT json_build_object('kind','table','table','" + table + "','rows',count(*),'digest',"
                       "encode(sha256(convert_to(COALESCE(string_agg(to_jsonb(t)::text,E'\\n' ORDER BY " + order + "),''),'UTF8')),'hex')) FROM " + table + " t")
    for history, table, limit in (("main", "public.flyway_schema_history", 9), ("agent", "public.flyway_agent_schema_history", 10)):
        queries.append("SELECT json_build_object('kind','migration','history','" + history + "',"
                       "'version',version,'installed_rank',installed_rank,'type',type,'script',script,"
                       "'checksum',checksum,'success',success,'digest'," + row_digest() + ") FROM " + table +
                       " t ORDER BY installed_rank LIMIT " + str(limit))
    queries.append("SELECT json_build_object('kind','audit','id',id,'action',action,'projectId',project_id,"
                   "'traceId',trace_id,'digest'," + row_digest() + ") FROM audit.audit_records t ORDER BY id LIMIT 5001")
    queries.append("SELECT json_build_object('kind','state','queued',count(*) FILTER (WHERE state='QUEUED'),"
                   "'running',count(*) FILTER (WHERE state='RUNNING')) FROM agent.requests")
    queries.append("COMMIT")
    return ";".join(queries) + ";"


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value)
        value[key] = item
    return value


def strict_json(raw):
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=lambda _: require(False))


def database_snapshot():
    try:
        result = subprocess.run(["docker", "exec", "archguard-agent-4h-postgres-1", "psql", "-X", "-q",
                                 "-U", "archguard", "-d", "archguard", "-v", "ON_ERROR_STOP=1", "-A", "-t",
                                 "-c", snapshot_sql()], capture_output=True, text=True, check=False, timeout=15)
        require(result.returncode == 0 and len(result.stdout.encode("utf-8")) <= MAX_BYTES)
        lines = result.stdout.splitlines()
        require(0 < len(lines) <= MAX_AUDIT_ROWS + 42)
        return parse_database_snapshot([strict_json(line) for line in lines])
    except (AssertionError, OSError, subprocess.SubprocessError, ValueError, TypeError, UnicodeError, RecursionError):
        raise AssertionError("FINAL_HISTORY_DATABASE_FAILED") from None


# Constant script, no path interpolation, no ACL/SID output and no mutations.
WINDOWS_ACL_QUERY = r"""
$ErrorActionPreference='Stop'
$env:PSModulePath=$PSHOME+'\Modules'
try {
  $p=$env:ARCHGUARD_PRIVATE_PATH
  $item=Get-Item -LiteralPath $p -Force
  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'unsafe' }
  $acl=Get-Acl -LiteralPath $p
  $current=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $current) { throw 'unsafe' }
  foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
    if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
        $rule.IdentityReference.Value -ne $current -and $rule.IdentityReference.Value -ne 'S-1-5-18') { throw 'unsafe' }
  }
  [Console]::Out.WriteLine('true')
} catch { [Console]::Out.WriteLine('false') }
"""


def windows_private_acl(path):
    try:
        environment = os.environ.copy()
        environment["ARCHGUARD_PRIVATE_PATH"] = str(path)
        result = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_ACL_QUERY],
                                env=environment, capture_output=True, text=True, check=False, timeout=5)
        return result.returncode == 0 and result.stdout in ("true\n", "true\r\n") and not result.stderr
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def no_links(path):
    require(path.is_absolute() and path == path.resolve(strict=True))
    for part in (path, *path.parents):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode))
        require(not (getattr(info, "st_file_attributes", 0) & 0x400))


def require_private_path(path, directory=False):
    no_links(path)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
    if os.name == "nt":
        require(windows_private_acl(path))
    elif os.name == "posix":
        require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600))
    else:
        require(False)
    return info.st_dev, info.st_ino


def read_local_json(path, private=True):
    require(path.parent == PRIVATE_DIR)
    parent = require_private_path(PRIVATE_DIR, True) if private else None
    if private:
        require_private_path(path)
    else:
        no_links(path)
        require(stat.S_ISREG(path.lstat().st_mode))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_BYTES)
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(fd)
        require(0 < len(raw) <= MAX_BYTES)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns))
        require((after.st_dev, after.st_ino) == (path.lstat().st_dev, path.lstat().st_ino))
        if private:
            require(require_private_path(PRIVATE_DIR, True) == parent)
            require_private_path(path)
        return strict_json(raw.decode("utf-8", errors="strict"))
    finally:
        os.close(fd)


def write_capture(snapshot):
    require(SNAPSHOT_FILE.parent == PRIVATE_DIR)
    parent = require_private_path(PRIVATE_DIR, True)
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    require(len(raw) <= MAX_BYTES)
    fd = os.open(SNAPSHOT_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) |
                 getattr(os, "O_BINARY", 0), 0o600)
    try:
        require_private_path(SNAPSHOT_FILE)
        require(require_private_path(PRIVATE_DIR, True) == parent)
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            require(type(written) is int and 0 < written <= len(raw) - offset)
            offset += written
        os.fsync(fd)
        require_private_path(SNAPSHOT_FILE)
        require(require_private_path(PRIVATE_DIR, True) == parent)
    finally:
        os.close(fd)
    require(read_local_json(SNAPSHOT_FILE) == snapshot)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("capture", "old", "restored"))
    parser.add_argument("--validate-only", action="store_true", help="Validate without writing or claiming a protected capture")
    args = parser.parse_args(argv)
    try:
        candidate = read_local_json(MANIFEST_FILE, private=not args.validate_only)
        validate_manifest(candidate)
        # Refuse an existing capture before reading the DB. No overwrite/retry.
        if args.phase == "capture" and not args.validate_only:
            require(not os.path.lexists(SNAPSHOT_FILE))
        baseline = None
        if args.phase != "capture":
            baseline = read_local_json(SNAPSHOT_FILE, private=not args.validate_only)
            validate_snapshot(baseline, candidate)
        current = database_snapshot()
        validate_database(current)
        if baseline is not None:
            assert_unchanged(baseline["database"], current, candidate.get("allowedAuditAppends", ()))
        if args.phase == "capture" and not args.validate_only:
            write_capture({"schemaVersion": SCHEMA_VERSION, "kind": KIND, "manifest": candidate, "database": current})
        print(json.dumps({"phase": args.phase, "validatedOnly": args.validate_only,
                          "runtimeCapturePassed": args.phase == "capture" and not args.validate_only,
                          "historyUnchanged": baseline is not None, "historicalTables": 21, "realModelCalls": 0}, sort_keys=True))
        return 0
    except (AssertionError, OSError, ValueError, TypeError, UnicodeError, RecursionError):
        print(json.dumps({"category": "FINAL_HISTORY_UNAVAILABLE", "runtimeCapturePassed": False}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
