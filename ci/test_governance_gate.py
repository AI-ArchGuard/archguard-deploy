import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.error

import governance_gate as gate


class GovernanceGateTest(unittest.TestCase):
    def test_submission_retries_transient_failure_with_same_idempotency_key_and_body(self):
        requests = []

        def respond(request, timeout):
            requests.append(request)
            if len(requests) == 1:
                raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)
            return io.BytesIO(b'{"id":"submission-1"}')

        with mock.patch.object(gate.urllib.request, "urlopen", side_effect=respond), \
                mock.patch.object(gate.time, "sleep") as sleep:
            result = gate.submit("https://example.invalid/report-submissions", "secret", "stable-key",
                                 {"reportSha256": "abc"}, b'{}')
        self.assertEqual("submission-1", result["id"])
        self.assertEqual(2, len(requests))
        self.assertEqual(requests[0].data, requests[1].data)
        self.assertEqual("stable-key", requests[0].get_header("Idempotency-key"))
        self.assertEqual("stable-key", requests[1].get_header("Idempotency-key"))
        sleep.assert_called_once()

    def test_submission_does_not_retry_authorization_failure(self):
        with mock.patch.object(gate.urllib.request, "urlopen", side_effect=urllib.error.HTTPError(
                "https://example.invalid", 401, "Unauthorized", {}, None)) as api, \
                mock.patch.object(gate.time, "sleep") as sleep:
            with self.assertRaises(gate.GateFailure) as failure:
                gate.submit("https://example.invalid", "secret", "stable-key", {}, b'{}')
        self.assertEqual(70, failure.exception.exit_code)
        self.assertEqual(1, api.call_count)
        sleep.assert_not_called()

    def test_status_publication_retries_transient_failure_only(self):
        with mock.patch.object(gate.urllib.request, "urlopen", side_effect=[
                urllib.error.HTTPError("https://example.invalid", 429, "Rate limited", {}, None),
                io.BytesIO(b'{"state":"success"}')]) as api, \
                mock.patch.object(gate.time, "sleep") as sleep:
            gate.publish_status("https://example.invalid", "secret", {"state": "success"})
        self.assertEqual(2, api.call_count)
        sleep.assert_called_once()

    def test_exhausted_status_retry_returns_seventy_without_exposing_token(self):
        def unavailable(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)

        with mock.patch.object(gate.urllib.request, "urlopen", side_effect=unavailable) as api, \
                mock.patch.object(gate.time, "sleep") as sleep:
            with self.assertRaises(gate.GateFailure) as failure:
                gate.publish_status("https://example.invalid", "private-token", {"state": "failure"})
        self.assertEqual(70, failure.exception.exit_code)
        self.assertNotIn("private-token", str(failure.exception))
        self.assertEqual(3, api.call_count)
        self.assertEqual(2, sleep.call_count)

    def test_pull_request_uses_head_not_merge_commit(self):
        head, base = "a" * 40, "b" * 40
        event = {"pull_request": {"number": 17, "head": {"sha": head},
                                  "base": {"sha": base, "ref": "main"}}}
        revision, reference = gate.revision_from_event("pull_request", event, "123", "c" * 40, "17/merge")
        self.assertEqual(head, revision["commitSha"])
        self.assertEqual("main", revision["targetBranch"])
        self.assertEqual({"externalId": "17", "headSha": head, "baseSha": base}, reference)

    def test_push_uses_exact_commit(self):
        revision, reference = gate.revision_from_event("push", {}, "123", "a" * 40, "main")
        self.assertEqual("a" * 40, revision["commitSha"])
        self.assertIsNone(reference)

    def test_push_rejects_checkout_that_is_not_claimed_commit(self):
        with mock.patch.object(gate.subprocess, "run", return_value=subprocess.CompletedProcess(
                ["git"], 0, stdout="b" * 40 + "\n")):
            with self.assertRaises(gate.GateFailure) as failure:
                gate.require_checkout_revision(Path("/workspace"), "a" * 40)
        self.assertEqual(64, failure.exception.exit_code)

    def test_invalid_commit_fails_configuration(self):
        with self.assertRaises(gate.GateFailure) as failure:
            gate.revision_from_event("push", {}, "123", "not-a-sha", "main")
        self.assertEqual(64, failure.exception.exit_code)

    def test_multipart_keeps_raw_report_bytes_and_digest(self):
        report = b'{"schemaVersion":"0.1.0"}\n'
        metadata = {"reportSha256": hashlib.sha256(report).hexdigest()}
        content_type, body = gate.multipart(metadata, report)
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(json.dumps(metadata, separators=(",", ":")).encode(), body)
        self.assertIn(report, body)

    def test_new_violation_exits_two_and_repair_exits_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "scanner.jar").write_bytes(b"pinned-test-scanner")
            (root / "rules.yaml").write_text("rules: []", encoding="utf-8")
            (root / "event.json").write_text("{}", encoding="utf-8")
            env = {"ARCHGUARD_PLATFORM_URL": "http://127.0.0.1:8080",
                   "ARCHGUARD_PROJECT_ID": "11111111-1111-1111-1111-111111111111",
                   "ARCHGUARD_REPOSITORY_ID": "22222222-2222-2222-2222-222222222222",
                   "ARCHGUARD_RULESET_VERSION_ID": "33333333-3333-3333-3333-333333333333",
                   "ARCHGUARD_SCANNER_JAR": str(root / "scanner.jar"),
                   "ARCHGUARD_RULES_FILE": str(root / "rules.yaml"),
                   "ARCHGUARD_CI_TOKEN": "test-token", "GITHUB_TOKEN": "test-github-token",
                   "GITHUB_WORKSPACE": str(root), "GITHUB_EVENT_NAME": "push",
                   "GITHUB_EVENT_PATH": str(root / "event.json"),
                   "GITHUB_REPOSITORY_ID": "123", "GITHUB_REPOSITORY": "example/repo",
                   "GITHUB_SHA": "a" * 40, "GITHUB_REF_NAME": "main", "RUNNER_TEMP": str(root)}

            def scan(args, **kwargs):
                if args[0] == "git":
                    return subprocess.CompletedProcess(args, 0, stdout="a" * 40 + "\n")
                (root / "archguard-governance-report.json").write_bytes(b'{}')
                return subprocess.CompletedProcess(args, 2)

            with mock.patch.dict(os.environ, env), mock.patch.object(gate.subprocess, "run", side_effect=scan), \
                    mock.patch.object(gate, "submit", return_value={"id": "submission-1"}), \
                    mock.patch.object(gate, "await_gate") as gate_result, \
                    mock.patch.object(gate, "publish_status") as api:
                for outcome, exit_code, state in (("FAIL", 2, "failure"), ("PASS", 0, "success")):
                    gate_result.return_value = {"submissionId": "submission-1",
                                                "revision": {"commitSha": "a" * 40},
                                                "ciExitCode": exit_code, "outcome": outcome}
                    api.reset_mock()
                    self.assertEqual(exit_code, gate.run())
                    self.assertEqual(state, api.call_args.args[2]["state"])

    def test_late_result_cannot_publish_newer_pr_head(self):
        with mock.patch.object(gate, "request_json", return_value={"headSha": "b" * 40,
                                                            "currentGateEvaluationId": "new-gate"}) as api:
            with self.assertRaises(gate.GateFailure) as failure:
                gate.await_current_head("https://example.invalid/pr", "token", "a" * 40, "old-gate")
            self.assertEqual(70, failure.exception.exit_code)
            self.assertEqual(1, api.call_count)


if __name__ == "__main__":
    unittest.main()
