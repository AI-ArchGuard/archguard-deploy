"""Independent, offline contract for final personal-live rollback evidence.

The historical synthetic nine-table tests deliberately remain separate.
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).with_name("verify-agent-live-rollback.py")
rollback = None
if MODULE_PATH.is_file():
    spec = importlib.util.spec_from_file_location("personal_live_rollback", MODULE_PATH)
    rollback = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rollback)

# These literal expectations come from the migration/spec inventory, never TABLES.
EXPECTED_TABLES = {
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
PROJECT = "11111111-1111-4111-8111-111111111111"
AUDIT_ID = "22222222-2222-4222-8222-222222222222"
NEW_AUDIT_ID = "33333333-3333-4333-8333-333333333333"
TRACE = "1" * 32
SENSITIVE = "PRIVATE_RAW_BODY_DO_NOT_ECHO"


def migrations():
    def sql(version, rank, script):
        return {"version": str(version), "installed_rank": rank, "type": "SQL",
                "script": script, "checksum": 173 * version, "success": True,
                "digest": "b" * 64}
    main = [sql(n, n, script) for n, script in enumerate(MAIN_SCRIPTS, 1)]
    agent = [{"version": "8", "installed_rank": 1, "type": "BASELINE",
              "script": "<< Flyway Baseline >>", "checksum": None, "success": True,
              "digest": "c" * 64}]
    agent.extend(sql(n, n - 7, script) for n, script in enumerate(AGENT_SCRIPTS, 9))
    return main, agent


def records():
    main, agent = migrations()
    result = [{"kind": "table", "table": table, "rows": 1, "digest": "a" * 64}
              for table in EXPECTED_TABLES]
    result[0]["rows"] = 8
    result[1]["rows"] = 9
    result.extend({"kind": "migration", "history": history, **row}
                  for history, rows in (("main", main), ("agent", agent)) for row in rows)
    result.append({"kind": "audit", "id": AUDIT_ID, "action": "agent.request.succeeded",
                   "projectId": PROJECT, "traceId": TRACE, "digest": "d" * 64})
    result.append({"kind": "state", "queued": 0, "running": 0})
    return result


def manifest():
    return {"schemaVersion": "0.1.0", "kind": "PERSONAL_LIVE_FINAL_ROLLBACK",
            "deploymentId": "44444444-4444-4444-8444-444444444444",
            "candidates": {
                "docs": "077a7c5afa12557543ee04e14321701c3537931a",
                "platform": "af821fc99553d462a2176cba5af70be7cc960c75",
                "web": "5c5a7a021210876cda55850d7898e11aa52781aa",
                "scanner": "d4b8e98bfdabbc78f65910ed37e3062167d04b07",
                "samples": "a53a5bbea2630aac2135aa217d961cdbb77851a3",
                "deploy": "5" * 40},
            "namespaceProofRef": "local-namespace-proof-1", "configProofRef": "closed-config-proof-1",
            "shutdownComplete": True}


class FinalHistoryContractTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(rollback, "RED: final personal-live rollback verifier is not implemented")

    def parse(self, values=None):
        return rollback.parse_database_snapshot(records() if values is None else values)

    def test_inventory_is_exact_independent_twenty_one_table_key_contract(self):
        self.assertEqual(rollback.TABLES, EXPECTED_TABLES)
        parsed = self.parse()
        self.assertEqual(set(parsed["tables"]), set(EXPECTED_TABLES))
        self.assertEqual(parsed["pendingRequests"], 0)
        self.assertEqual(set(parsed["audit"]), {AUDIT_ID})

    def test_parser_rejects_each_missing_extra_duplicate_and_bad_table_stat(self):
        for table in EXPECTED_TABLES:
            for mutation in ("missing", "duplicate", "negative", "boolean", "float", "digest", "uppercase"):
                values = records()
                index = next(n for n, row in enumerate(values) if row.get("table") == table)
                if mutation == "missing":
                    values.pop(index)
                elif mutation == "duplicate":
                    values.append(copy.deepcopy(values[index]))
                elif mutation in ("negative", "boolean", "float"):
                    values[index]["rows"] = {"negative": -1, "boolean": True, "float": 1.5}[mutation]
                else:
                    values[index]["digest"] = "a" * 32 if mutation == "digest" else "A" * 64
                with self.subTest(table=table, mutation=mutation), self.assertRaises(AssertionError):
                    self.parse(values)
        for extra in ({"kind": "table", "table": "agent.inventory_proof", "rows": 0, "digest": "a" * 64},
                      {"kind": "unknown"}, {"kind": "table", "table": SENSITIVE, "rows": 0, "digest": "a" * 64}):
            with self.assertRaises(AssertionError):
                self.parse(records() + [extra])

    def test_parser_accepts_present_empty_tables_but_rejects_nonquiescent_or_missing_state(self):
        values = records()
        next(row for row in values if row.get("table") == "agent.live_batch_stops")["rows"] = 0
        self.parse(values)
        for state in (None, {"kind": "state", "queued": 1, "running": 0},
                      {"kind": "state", "queued": 0, "running": 1},
                      {"kind": "state", "queued": False, "running": 0}):
            values = [row for row in records() if row["kind"] != "state"]
            if state is not None:
                values.append(state)
            with self.subTest(state=state), self.assertRaises(AssertionError):
                self.parse(values)
        with self.assertRaises(AssertionError):
            self.parse(records() + [{"kind": "state", "queued": 0, "running": 0}])

    def test_migration_exact_scripts_types_checksums_success_and_versions(self):
        main, agent = migrations()
        rollback.validate_migrations(main, agent)
        for history in ("main", "agent"):
            count = 8 if history == "main" else 9
            for index in range(count):
                for mutation in ("missing", "duplicate", "version", "script", "type", "checksum", "success", "digest", "rank"):
                    main, agent = migrations()
                    rows = main if history == "main" else agent
                    if mutation == "missing":
                        rows.pop(index)
                    elif mutation == "duplicate":
                        rows.append(copy.deepcopy(rows[index]))
                    else:
                        key, value = {"version": ("version", "99"), "script": ("script", "unreviewed.sql"),
                                      "type": ("type", "JDBC"), "checksum": ("checksum", None if index or history == "main" else 123),
                                      "success": ("success", False), "digest": ("digest", "broken"),
                                      "rank": ("installed_rank", 0)}[mutation]
                        rows[index][key] = value
                    with self.subTest(history=history, index=index, mutation=mutation), self.assertRaises(AssertionError):
                        rollback.validate_migrations(main, agent)

    def test_every_table_missing_deleted_appended_or_full_row_changed_fails(self):
        before = self.parse()
        rollback.assert_unchanged(before, copy.deepcopy(before))
        for table in EXPECTED_TABLES:
            for change in ("missing", "delete", "append", "digest"):
                after = copy.deepcopy(before)
                if change == "missing":
                    del after["tables"][table]
                elif change == "digest":
                    after["tables"][table]["digest"] = "f" * 64
                else:
                    after["tables"][table]["rows"] += 1 if change == "append" else -1
                with self.subTest(table=table, change=change), self.assertRaises(AssertionError):
                    rollback.assert_unchanged(before, after)

    def test_policy_proof_slot_day_revision_and_migration_only_mutations_fail(self):
        before = self.parse()
        # Server full-row digest must cover non-key values, not a handpicked projection.
        for label, table in (("policy", "agent.live_batches"), ("inventory_proof", "agent.live_batches"),
                             ("request_slot", "agent.live_template_request_slots"), ("utc_day", "agent.live_budget_usage"),
                             ("revision", "agent.project_settings")):
            after = copy.deepcopy(before)
            after["tables"][table]["digest"] = "e" * 64
            with self.subTest(column=label), self.assertRaises(AssertionError):
                rollback.assert_unchanged(before, after)
        after = copy.deepcopy(before)
        after["migrations"]["agent"][-1]["checksum"] += 1
        with self.assertRaises(AssertionError):
            rollback.assert_unchanged(before, after)

    def append(self, before, action="scanjob.created", project=PROJECT, trace=TRACE):
        after = copy.deepcopy(before)
        after["audit"][NEW_AUDIT_ID] = {"id": NEW_AUDIT_ID, "action": action, "projectId": project,
                                          "traceId": trace, "digest": "e" * 64}
        after["tables"]["audit.audit_records"] = {"rows": 2, "digest": "f" * 64}
        return after

    def test_audit_requires_every_baseline_uuid_and_digest_even_with_same_count(self):
        before = self.parse()
        for mutation in ("replace", "change", "delete"):
            after = copy.deepcopy(before)
            if mutation == "change":
                after["audit"][AUDIT_ID]["digest"] = "e" * 64
            elif mutation == "replace":
                after["audit"][NEW_AUDIT_ID] = after["audit"].pop(AUDIT_ID)
                after["audit"][NEW_AUDIT_ID]["id"] = NEW_AUDIT_ID
            else:
                del after["audit"][AUDIT_ID]
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                rollback.assert_unchanged(before, after, (("scanjob.created", PROJECT, TRACE),))

    def test_only_exact_approved_non_agent_append_passes_no_default_or_prefix(self):
        before = self.parse()
        after = self.append(before)
        rollback.assert_unchanged(before, after, (("scanjob.created", PROJECT, TRACE),))
        for approved in ((), (("scanjob.*", PROJECT, TRACE),), (("scanjob.created", NEW_AUDIT_ID, TRACE),),
                         (("scanjob.created", PROJECT, "2" * 32),)):
            with self.subTest(approved=approved), self.assertRaises(AssertionError):
                rollback.assert_unchanged(before, after, approved)
        for action in ("agent.request.succeeded", "agent_document.version.created", "AGENT_CREDENTIAL_STATUS",
                       "AGENT_CREDENTIAL_REPLACE", "agent.denied"):
            for project in (PROJECT, None):
                with self.subTest(action=action, project=project), self.assertRaises(AssertionError):
                    rollback.assert_unchanged(before, self.append(before, action, project), ((action, project, TRACE),))

    def test_audit_count_bound_and_safe_shapes_are_checked_independent_of_limit(self):
        for mutation in ("count", "duplicate", "uuid", "trace", "digest", "raw", "project"):
            values = records()
            audit = next(row for row in values if row["kind"] == "audit")
            if mutation == "count":
                next(row for row in values if row.get("table") == "audit.audit_records")["rows"] = 5001
            elif mutation == "duplicate":
                values.append(copy.deepcopy(audit))
            else:
                key, value = {"uuid": ("id", "bad"), "trace": ("traceId", "bad"),
                              "digest": ("digest", "bad"), "raw": ("metadata", SENSITIVE),
                              "project": ("projectId", "bad")}[mutation]
                audit[key] = value
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                self.parse(values)

    def test_manifest_accepts_exact_approved_1017_candidate_tuple(self):
        # Canonical merge SHAs are independent literals, never production CANDIDATES.
        rollback.validate_manifest(manifest())

    def test_manifest_and_snapshot_accept_exact_diagnostics_platform_candidate(self):
        candidate = manifest()
        candidate["candidates"]["platform"] = "af821fc99553d462a2176cba5af70be7cc960c75"
        snapshot = {"schemaVersion": "0.1.0", "kind": "PERSONAL_LIVE_FINAL_ROLLBACK",
                    "manifest": copy.deepcopy(candidate), "database": self.parse()}
        rollback.validate_manifest(candidate)
        rollback.validate_snapshot(snapshot, candidate)

    def test_manifest_and_snapshot_reject_previous_1017_platform_even_when_consistent(self):
        candidate = manifest()
        candidate["candidates"]["platform"] = "903ddc5987e0f6e63091ee4897d4311b9c41cbe9"
        snapshot = {"schemaVersion": "0.1.0", "kind": "PERSONAL_LIVE_FINAL_ROLLBACK",
                    "manifest": copy.deepcopy(candidate), "database": self.parse()}
        with self.assertRaises(AssertionError):
            rollback.validate_manifest(candidate)
        with self.assertRaises(AssertionError):
            rollback.validate_snapshot(snapshot, candidate)

    def test_manifest_rejects_old_engineering_tuple_with_other_fields_valid(self):
        candidate = manifest()
        candidate["candidates"].update({
            "docs": "0d0f5ede505f9afa6f369226eb7263ed123dfa3f",
            "platform": "9f68dea97fca7893961c8305ce84ff215be9d0df",
            "web": "961244ef3486967186cd4a41375fb29d25786043",
        })
        with self.assertRaises(AssertionError):
            rollback.validate_manifest(candidate)

    def test_manifest_pins_kind_proofs_actual_deploy_and_snapshot_binding(self):
        candidate = manifest()
        rollback.validate_manifest(candidate)
        snapshot = {"schemaVersion": "0.1.0", "kind": "PERSONAL_LIVE_FINAL_ROLLBACK",
                    "manifest": candidate, "database": self.parse()}
        rollback.validate_snapshot(snapshot, candidate)
        for key, value in (("schemaVersion", "1.0.0"), ("kind", "SYNTHETIC"),
                           ("shutdownComplete", False), ("namespaceProofRef", ""),
                           ("configProofRef", "https://example.invalid/raw"), ("deploymentId", "bad")):
            altered = copy.deepcopy(candidate)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                rollback.validate_manifest(altered)
        for name in ("docs", "platform", "web", "scanner", "samples", "deploy"):
            altered = copy.deepcopy(candidate)
            altered["candidates"][name] = "pending" if name == "deploy" else "0" * 40
            with self.subTest(candidate=name), self.assertRaises(AssertionError):
                rollback.validate_manifest(altered)
        changed = copy.deepcopy(candidate)
        changed["candidates"]["deploy"] = "6" * 40
        with self.assertRaises(AssertionError):
            rollback.validate_snapshot(snapshot, changed)
        for key in ("kind", "schemaVersion"):
            changed = copy.deepcopy(snapshot)
            changed[key] = "old"
            with self.assertRaises(AssertionError):
                rollback.validate_snapshot(changed, candidate)

    def test_database_process_is_fixed_readonly_bounded_and_never_echoes_raw_errors(self):
        observed = []
        payload = "\n".join(json.dumps(row) for row in records())
        def process(args, **kwargs):
            observed.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, payload, "")
        with mock.patch.object(rollback.subprocess, "run", side_effect=process):
            rollback.database_snapshot()
        self.assertEqual(len(observed), 1)
        args, kwargs = observed[0]
        self.assertEqual(args[:4], ["docker", "exec", "archguard-agent-4h-postgres-1", "psql"])
        self.assertIn("-X", args)
        self.assertIn("ON_ERROR_STOP=1", args)
        self.assertIn("archguard", args)
        self.assertGreater(kwargs["timeout"], 0)
        self.assertLessEqual(kwargs["timeout"], 15)
        self.assertFalse(kwargs.get("shell", False))
        sql = args[args.index("-c") + 1]
        folded = " ".join(sql.upper().split())
        self.assertIn("REPEATABLE READ", folded)
        self.assertIn("READ ONLY", folded)
        self.assertIn("STATEMENT_TIMEOUT", folded)
        self.assertIn("LOCK_TIMEOUT", folded)
        self.assertIn("5S", folded)
        self.assertIn("UTC", folded)
        self.assertEqual(folded.count("BEGIN"), 1)
        self.assertEqual(folded.count("COMMIT"), 1)
        self.assertIn("SHA256", folded)
        self.assertIn("TO_JSONB(T)", folded)
        self.assertNotIn("MD5(", folded)
        self.assertNotIn("SELECT *", folded)
        self.assertNotIn("AGENT_CREDENTIAL", folded)
        self.assertNotIn("LIKE 'AGENT.%'", folded)
        for table, order in EXPECTED_TABLES.items():
            self.assertIn(table.upper(), folded)
            self.assertIn("ORDER BY " + order.upper(), folded.replace(", ", ","))
        for failure in (subprocess.CompletedProcess([], 1, SENSITIVE, SENSITIVE),
                        subprocess.TimeoutExpired("docker", 15, output=SENSITIVE, stderr=SENSITIVE),
                        subprocess.CompletedProcess([], 0, SENSITIVE, SENSITIVE)):
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(rollback.subprocess, "run", side_effect=failure if isinstance(failure, Exception) else None,
                                   return_value=failure), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(AssertionError) as caught:
                    rollback.database_snapshot()
            self.assertNotIn(SENSITIVE, str(caught.exception) + out.getvalue() + err.getvalue())

    def test_fixed_cli_rejects_arbitrary_targets_and_supports_no_write_validation(self):
        self.assertEqual(rollback.PRIVATE_DIR, rollback.ROOT / ".local/agent-personal-live")
        self.assertEqual(rollback.MANIFEST_FILE, rollback.PRIVATE_DIR / "candidate.json")
        self.assertEqual(rollback.SNAPSHOT_FILE, rollback.PRIVATE_DIR / "rollback-history.json")
        with tempfile.TemporaryDirectory() as temp:
            # Hosted Windows TEMP may use a short-name alias. Supply a real
            # canonical fixture while retaining the production no-links rule.
            private = Path(temp).resolve(strict=True)
            candidate = private / "candidate.json"
            capture = private / "rollback-history.json"
            candidate.write_text(json.dumps(manifest()), encoding="utf-8")
            with mock.patch.multiple(rollback, PRIVATE_DIR=private, MANIFEST_FILE=candidate, SNAPSHOT_FILE=capture), \
                    mock.patch.object(rollback, "database_snapshot", return_value=self.parse()), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(rollback.main(["capture", "--validate-only"]), 0)
            self.assertFalse(capture.exists())
            result = json.loads(output.getvalue())
            self.assertTrue(result["validatedOnly"])
            self.assertFalse(result["runtimeCapturePassed"])
        for option in ("--snapshot", "--manifest", "--container", "--sql", "--runtime-root", "--base-url"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                rollback.main(["capture", option, SENSITIVE])

    def test_windows_acl_query_is_bounded_readonly_boolean_and_path_is_never_interpolated(self):
        path = Path("C:/private/quote';&-raw-path.json")
        observed = []
        def process(args, **kwargs):
            observed.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, "true\n", "")
        with mock.patch.object(rollback.subprocess, "run", side_effect=process):
            self.assertTrue(rollback.windows_private_acl(path))
        self.assertEqual(len(observed), 1)
        args, kwargs = observed[0]
        self.assertEqual(args[:4], ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive"])
        self.assertIn("-Command", args)
        self.assertNotIn(str(path), " ".join(args))
        self.assertEqual(kwargs["env"]["ARCHGUARD_PRIVATE_PATH"], str(path))
        self.assertGreater(kwargs["timeout"], 0)
        self.assertLessEqual(kwargs["timeout"], 5)
        self.assertFalse(kwargs.get("shell", False))
        for result in (subprocess.CompletedProcess([], 0, "false\n", ""),
                       subprocess.CompletedProcess([], 0, '{"private":true}', ""),
                       subprocess.CompletedProcess([], 0, "true\n" + SENSITIVE, ""),
                       subprocess.CompletedProcess([], 1, SENSITIVE, SENSITIVE),
                       subprocess.TimeoutExpired("powershell.exe", 5, output=SENSITIVE),
                       FileNotFoundError(SENSITIVE)):
            with mock.patch.object(rollback.subprocess, "run", side_effect=result if isinstance(result, Exception) else None,
                                   return_value=result), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertFalse(rollback.windows_private_acl(path))
            self.assertNotIn(SENSITIVE, output.getvalue())

    @unittest.skipUnless(os.name == "posix", "native POSIX capture; root also verifies Windows private ACLs")
    def test_native_capture_private_exclusive_and_rejects_unsafe_or_linked_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            private = Path(temp) / "private"
            private.mkdir(mode=0o700)
            candidate = private / "candidate.json"
            capture = private / "rollback-history.json"
            candidate.write_text(json.dumps(manifest()), encoding="utf-8")
            candidate.chmod(0o600)
            with mock.patch.multiple(rollback, PRIVATE_DIR=private, MANIFEST_FILE=candidate, SNAPSHOT_FILE=capture), \
                    mock.patch.object(rollback, "database_snapshot", return_value=self.parse()), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(rollback.main(["capture"]), 0)
                original = capture.read_bytes()
                self.assertEqual(capture.stat().st_mode & 0o777, 0o600)
                self.assertNotEqual(rollback.main(["capture"]), 0)
                self.assertEqual(capture.read_bytes(), original)
                capture.chmod(0o644)
                self.assertNotEqual(rollback.main(["old"]), 0)
                capture.chmod(0o600)
                private.chmod(0o755)
                self.assertNotEqual(rollback.main(["restored"]), 0)
                private.chmod(0o700)
                capture.unlink()
                capture.symlink_to(candidate)
                self.assertNotEqual(rollback.main(["capture"]), 0)
                self.assertEqual(candidate.read_text(encoding="utf-8"), json.dumps(manifest()))

    @unittest.skipUnless(os.name == "nt", "Windows denied ACLs cannot write; root exercises actual private ACL fixture")
    def test_windows_denied_or_unavailable_acl_query_cannot_claim_runtime_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            private = Path(temp)
            candidate = private / "candidate.json"
            capture = private / "rollback-history.json"
            candidate.write_text(json.dumps(manifest()), encoding="utf-8")
            with mock.patch.multiple(rollback, PRIVATE_DIR=private, MANIFEST_FILE=candidate, SNAPSHOT_FILE=capture), \
                    mock.patch.object(rollback, "windows_private_acl", return_value=False), \
                    mock.patch.object(rollback, "database_snapshot", return_value=self.parse()), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertNotEqual(rollback.main(["capture"]), 0)
            self.assertFalse(capture.exists())
            self.assertNotIn('"runtimeCapturePassed": true', output.getvalue())

    @unittest.skipUnless(os.name == "nt", "native Windows trusted-module ACL regression")
    def test_windows_private_acl_ignores_hostile_inherited_module_path(self):
        # Only this newly created synthetic directory receives ACL changes.
        # The production ACL query must resolve the trusted Windows module even
        # when the calling shell exports an existing incompatible module path.
        setup = r"""
$ErrorActionPreference='Stop'
$env:PSModulePath=$PSHOME+'\Modules'
try {
  $p=$env:ARCHGUARD_ACL_TEST_PATH
  $acl=[System.Security.AccessControl.DirectorySecurity]::new()
  $owner=[System.Security.Principal.WindowsIdentity]::GetCurrent().User
  $system=[System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
  $acl.SetOwner($owner)
  $acl.SetAccessRuleProtection($true,$false)
  foreach ($sid in @($owner,$system)) {
    $rule=[System.Security.AccessControl.FileSystemAccessRule]::new(
      $sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
    $acl.AddAccessRule($rule)
  }
  Set-Acl -LiteralPath $p -AclObject $acl
  [Console]::Out.WriteLine('true')
} catch { [Console]::Out.WriteLine('false') }
"""
        with tempfile.TemporaryDirectory(prefix="archguard-acl-regression-") as temp:
            private = Path(temp) / "new-private-fixture"
            private.mkdir()
            environment = os.environ.copy()
            environment["ARCHGUARD_ACL_TEST_PATH"] = str(private)
            configured = subprocess.run(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", setup],
                env=environment, capture_output=True, text=True, check=False, timeout=5)
            self.assertEqual(configured.returncode, 0, "Synthetic private ACL setup failed")
            self.assertEqual(configured.stdout.strip(), "true", "Synthetic private ACL setup was denied")
            self.assertFalse(configured.stderr, "Synthetic private ACL setup emitted an error")
            with self.subTest(module_path="actual-inherited-environment"):
                self.assertTrue(rollback.windows_private_acl(private),
                                "Private owner/SYSTEM ACL must validate under the actual inherited shell environment")
            module_root = Path(temp) / "existing-incompatible-modules"
            module = module_root / "Microsoft.PowerShell.Security"
            module.mkdir(parents=True)
            # Data-only incompatible manifest; no module or executable fixture code.
            (module / "Microsoft.PowerShell.Security.psd1").write_text(
                "@{ ModuleVersion='1.0.0'; PowerShellVersion='99.0'; "
                "FunctionsToExport=@('Get-Acl'); CmdletsToExport=@('Get-Acl') }\n",
                encoding="ascii")
            environment = {key: value for key, value in os.environ.items() if key.lower() != "psmodulepath"}
            environment["PSModulePath"] = str(module_root)
            with mock.patch.dict(rollback.os.environ, environment, clear=True), \
                    self.subTest(module_path="existing-incompatible-data-only-module"):
                self.assertTrue(rollback.windows_private_acl(private),
                                "Private owner/SYSTEM ACL must validate despite an existing incompatible module path")


if __name__ == "__main__":
    unittest.main()
