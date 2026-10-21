"""Offline tests for a fixed-path, new-volume-only inventory initializer."""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).with_name("initialize-agent-inventory.py")
inventory = None
if MODULE_PATH.is_file():
    spec = importlib.util.spec_from_file_location("agent_inventory_initializer", MODULE_PATH)
    inventory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inventory)

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
PRIVATE = "PRIVATE_INVENTORY_CONTENT_DO_NOT_ECHO"


def fixture():
    return {"schemaVersion": "0.1.0", "deploymentId": "11111111-1111-4111-8111-111111111111",
            "entries": [{"inventoryId": "22222222-2222-4222-8222-222222222222",
                         "projectId": "33333333-3333-4333-8333-333333333333",
                         "manifestSha256": "a" * 64, "sourceKind": "CONTROLLED_SYNTHETIC_FIXTURES",
                         "fixtureSetVersion": "synthetic-fixtures-1", "fixtureArtifactSha256": "b" * 64,
                         "reviewRef": "synthetic-review-1", "reviewedAt": "2026-10-18T11:00:00Z",
                         "expiresAt": "2026-10-19T11:00:00Z"}]}


def encoded(value=None):
    return json.dumps(fixture() if value is None else value, separators=(",", ":")).encode("utf-8")


def new_generation():
    value = fixture()
    value['entries'][0].update(inventoryId='44444444-4444-4444-8444-444444444444',
                              reviewRef='synthetic-review-new', reviewedAt='2026-10-19T12:00:00Z',
                              expiresAt='2026-10-20T12:00:00Z')
    return value


class InventoryContentContractTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(inventory, "RED: fixed-path inventory initializer is not implemented")

    def test_valid_bytes_are_validated_without_manufacturing_review_or_approval(self):
        raw = encoded()
        self.assertEqual(inventory.validate_inventory(raw, NOW), fixture())
        self.assertEqual(raw, encoded())
        self.assertEqual(inventory.REVIEW_FILE, Path("/reviewed/inventory.json"))
        self.assertEqual(inventory.VOLUME_DIR, Path("/inventory"))
        self.assertEqual(inventory.DESTINATION, Path("/inventory/inventory.json"))

    def test_independent_current_generation_does_not_extend_expired_archive_or_accept_appended_entry(self):
        old = encoded()
        current = new_generation()
        later = NOW + timedelta(days=1)
        self.assertEqual(inventory.validate_inventory(encoded(current), later), current)
        with self.assertRaises(AssertionError):
            inventory.validate_inventory(old, later)
        current['entries'].append(fixture()['entries'][0])
        with self.assertRaises(AssertionError):
            inventory.validate_inventory(encoded(current), later)
        self.assertEqual(old, encoded())

    def test_json_utf8_bounds_duplicates_and_unknown_fields_fail_closed(self):
        raw = encoded()
        self.assertEqual(inventory.validate_inventory(raw + b" " * (32768 - len(raw)), NOW), fixture())
        invalid = (b"", b" " * 32769, b"\xff", b"\xef\xbb\xbf" + raw, raw + b" {}",
                   b'{"schemaVersion":"0.1.0","schemaVersion":"0.1.0"}',
                   raw.replace(b'"reviewRef":', b'"reviewRef":"duplicate","reviewRef":'),
                   b"[]", b"null", b"true", b"1", b"{" + b"[" * 5000)
        for value in invalid:
            with self.subTest(value_length=len(value)), self.assertRaises(AssertionError):
                inventory.validate_inventory(value, NOW)
        for where in ("root", "entry"):
            value = fixture()
            (value if where == "root" else value["entries"][0])["unknown"] = PRIVATE
            with self.subTest(where=where), self.assertRaises(AssertionError):
                inventory.validate_inventory(encoded(value), NOW)

    def test_every_required_root_and_entry_field_is_required(self):
        for root in (True, False):
            source = fixture() if root else fixture()["entries"][0]
            for key in source:
                value = fixture()
                del (value if root else value["entries"][0])[key]
                with self.subTest(root=root, key=key), self.assertRaises(AssertionError):
                    inventory.validate_inventory(encoded(value), NOW)

    def test_strict_uuid_digest_reference_source_kind_schema_and_scalar_types(self):
        cases = {
            "inventoryId": ["bad", "22222222222242228222222222222222", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", None, 1],
            "projectId": ["bad", None], "manifestSha256": ["a" * 63, "A" * 64, None],
            "fixtureArtifactSha256": ["b" * 65, "B" * 64],
            "sourceKind": ["SYNTHETIC", "REAL", True],
            "fixtureSetVersion": ["", "a" * 129, "../path", "https://example.invalid", "SK-private", "GHP_private", "GITHUB_PAT_private"],
            "reviewRef": ["", "a b", "a/b", "a\\b", "sk-private", "ghp_private", "github_pat_private", None],
        }
        for key, invalid in cases.items():
            for replacement in invalid:
                value = fixture()
                value["entries"][0][key] = replacement
                with self.subTest(field=key, replacement=replacement), self.assertRaises(AssertionError):
                    inventory.validate_inventory(encoded(value), NOW)
        for key, replacement in (("schemaVersion", "1.0.0"), ("deploymentId", "bad"),
                                 ("entries", {}), ("entries", []), ("entries", [None])):
            value = fixture()
            value[key] = replacement
            with self.subTest(root=key), self.assertRaises(AssertionError):
                inventory.validate_inventory(encoded(value), NOW)

    def test_explicit_utc_clock_review_expiry_and_twenty_four_hour_boundary(self):
        cases = (("reviewedAt", "2026-10-18T12:00:01Z"), ("expiresAt", "2026-10-18T12:00:00Z"),
                 ("expiresAt", "2026-10-18T10:59:59Z"), ("expiresAt", "2026-10-19T11:00:01Z"),
                 ("reviewedAt", "2026-10-18T11:00:00"), ("reviewedAt", "not-time"),
                 ("expiresAt", True))
        for key, replacement in cases:
            value = fixture()
            value["entries"][0][key] = replacement
            with self.subTest(field=key, replacement=replacement), self.assertRaises(AssertionError):
                inventory.validate_inventory(encoded(value), NOW)
        with self.assertRaises(AssertionError):
            inventory.validate_inventory(encoded(), datetime(2026, 10, 18, 12))
        inventory.validate_inventory(encoded(), NOW)  # Exactly 24 hours is permitted.

    def test_all_entries_checked_unique_inventory_ids_and_maximum_twenty(self):
        value = fixture()
        value["entries"] = [dict(value["entries"][0], inventoryId=f"{n:08x}-2222-4222-8222-222222222222")
                            for n in range(20)]
        self.assertEqual(len(inventory.validate_inventory(encoded(value), NOW)["entries"]), 20)
        for mutation in ("too-many", "duplicate", "invalid-last"):
            changed = copy.deepcopy(value)
            if mutation == "too-many":
                changed["entries"].append(dict(changed["entries"][0], inventoryId="ffffffff-2222-4222-8222-222222222222"))
            elif mutation == "duplicate":
                changed["entries"][-1]["inventoryId"] = changed["entries"][0]["inventoryId"]
            else:
                changed["entries"][-1]["reviewRef"] = "sk-private"
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                inventory.validate_inventory(encoded(changed), NOW)

    def test_cli_accepts_only_fixed_initialize_verify_actions_no_arbitrary_target(self):
        for args in (("rotate",), ("initialize", "--source", PRIVATE), ("verify", "--destination", PRIVATE),
                     ("initialize", "--command", PRIVATE), ("verify", "--url", PRIVATE)):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                inventory.main(list(args))


@unittest.skipUnless(os.name == "posix", "native modes require POSIX; root also runs Linux volume fixture")
class InventoryFilesystemContractTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(inventory, "RED: fixed-path inventory initializer is not implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "reviewed.json"
        self.source.write_bytes(encoded())
        self.volume = self.root / "volume"
        self.volume.mkdir(mode=0o755)
        self.destination = self.volume / "inventory.json"
        self.paths = mock.patch.multiple(inventory, REVIEW_FILE=self.source, VOLUME_DIR=self.volume, DESTINATION=self.destination)
        self.paths.start()
        self.addCleanup(self.paths.stop)
        def cleanup():
            if self.volume.exists() and not self.volume.is_symlink():
                self.volume.chmod(0o755)
            self.temp.cleanup()
        self.addCleanup(cleanup)

    def test_initialize_preserves_exact_bytes_and_sets_native_final_modes(self):
        original = self.source.read_bytes()
        inventory.initialize(now=NOW)
        self.assertEqual(self.destination.read_bytes(), original)
        self.assertEqual(self.volume.stat().st_mode & 0o777, 0o555)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o444)
        self.assertEqual(list(self.volume.iterdir()), [self.destination])
        inventory.verify(now=NOW)
        self.assertEqual(self.source.read_bytes(), original)

    def test_only_independent_new_empty_directory_initializes_while_expired_archive_is_unchanged(self):
        inventory.initialize(now=NOW)
        old_bytes = self.destination.read_bytes()
        old_modes = (self.volume.stat().st_mode, self.destination.stat().st_mode)
        later = NOW + timedelta(days=1)
        with self.assertRaises(AssertionError):
            inventory.verify(now=later)
        new_volume = self.root / 'new-volume'
        new_volume.mkdir(mode=0o755)
        self.addCleanup(new_volume.chmod, 0o755)
        self.source.write_bytes(encoded(new_generation()))
        with mock.patch.multiple(inventory, VOLUME_DIR=new_volume, DESTINATION=new_volume / 'inventory.json'):
            inventory.initialize(now=later)
            inventory.verify(now=later)
        with self.assertRaises(AssertionError):
            inventory.initialize(now=later)
        self.assertEqual(self.destination.read_bytes(), old_bytes)
        self.assertEqual((self.volume.stat().st_mode, self.destination.stat().st_mode), old_modes)
        self.assertEqual((new_volume / 'inventory.json').read_bytes(), encoded(new_generation()))

    def test_partial_failure_refuses_retry_without_repairing_remaining_bytes_or_modes(self):
        original_write = os.write
        calls = 0
        def fail_after_partial(fd, data):
            nonlocal calls
            calls += 1
            if calls == 1:
                return original_write(fd, data[:17])
            raise OSError(PRIVATE)
        with mock.patch.object(inventory.os, 'write', side_effect=fail_after_partial):
            with self.assertRaises(AssertionError):
                inventory.initialize(now=NOW)
        before = (self.destination.read_bytes(), self.destination.stat().st_mode, self.volume.stat().st_mode)
        self.assertEqual(before[0], encoded()[:17])
        with self.assertRaises(AssertionError):
            inventory.initialize(now=NOW)
        self.assertEqual((self.destination.read_bytes(), self.destination.stat().st_mode, self.volume.stat().st_mode), before)

    def test_any_existing_entry_including_dotfile_directory_and_link_refuses_without_mutation(self):
        for kind in ("file", "dotfile", "directory", "symlink"):
            path = self.volume / (".keep" if kind == "dotfile" else "inventory.json")
            if kind == "directory":
                path.mkdir(mode=0o700)
            elif kind == "symlink":
                path.symlink_to(self.source)
            else:
                path.write_bytes(b"preserve-existing")
                path.chmod(0o640)
            before = path.lstat()
            with self.subTest(kind=kind), self.assertRaises(AssertionError):
                inventory.initialize(now=NOW)
            self.assertEqual(path.lstat().st_mode, before.st_mode)
            self.assertEqual(self.source.read_bytes(), encoded())
            if path.is_file() and not path.is_symlink():
                self.assertEqual(path.read_bytes(), b"preserve-existing")
            path.rmdir() if kind == "directory" else path.unlink()

    def test_source_and_volume_symlink_or_unsafe_parent_rejected(self):
        linked_source = self.root / "source-link"
        linked_source.symlink_to(self.source)
        with mock.patch.object(inventory, "REVIEW_FILE", linked_source), self.assertRaises(AssertionError):
            inventory.initialize(now=NOW)
        linked_volume = self.root / "volume-link"
        linked_volume.symlink_to(self.volume, target_is_directory=True)
        with mock.patch.multiple(inventory, VOLUME_DIR=linked_volume, DESTINATION=linked_volume / "inventory.json"), self.assertRaises(AssertionError):
            inventory.initialize(now=NOW)
        for mode in (0o777, 0o775):
            self.volume.chmod(mode)
            with self.subTest(mode=oct(mode)), self.assertRaises(AssertionError):
                inventory.initialize(now=NOW)
        self.volume.chmod(0o755)
        with mock.patch.object(inventory.os, "geteuid", return_value=10001), self.assertRaises(AssertionError):
            inventory.initialize(now=NOW)

    def test_verify_rejects_changed_content_modes_extra_entries_and_links_readonly(self):
        inventory.initialize(now=NOW)
        original = self.destination.read_bytes()
        self.destination.chmod(0o644)
        with self.assertRaises(AssertionError):
            inventory.verify(now=NOW)
        self.destination.chmod(0o444)
        self.volume.chmod(0o755)
        with self.assertRaises(AssertionError):
            inventory.verify(now=NOW)
        (self.volume / ".extra").write_bytes(b"extra")
        self.volume.chmod(0o555)
        with self.assertRaises(AssertionError):
            inventory.verify(now=NOW)
        self.assertEqual(self.destination.read_bytes(), original)

    def test_partial_writes_are_completed_and_fsynced_and_failure_is_not_hidden_or_cleaned(self):
        original_write = os.write
        with mock.patch.object(inventory.os, "write", side_effect=lambda fd, data: original_write(fd, data[:3])), \
                mock.patch.object(inventory.os, "fsync", wraps=os.fsync) as sync:
            inventory.initialize(now=NOW)
        self.assertEqual(self.destination.read_bytes(), encoded())
        self.assertTrue(sync.called)
        with self.assertRaises(AssertionError):
            inventory.initialize(now=NOW)

    def test_zero_write_and_io_failure_leave_explicit_failure_without_cleanup_or_retry(self):
        for failure in (0, OSError(PRIVATE)):
            with mock.patch.object(inventory.os, "write", side_effect=failure if isinstance(failure, Exception) else None,
                                   return_value=failure):
                with self.subTest(failure=type(failure).__name__), self.assertRaises(AssertionError) as caught:
                    inventory.initialize(now=NOW)
            self.assertNotIn(PRIVATE, str(caught.exception))
            self.assertTrue(self.destination.exists())
            self.assertEqual(self.destination.read_bytes(), b"")
            # Test-only reset; production must preserve a failed partial entry.
            self.destination.unlink()

    def test_invalid_input_and_failure_output_never_echo_content_ids_digest_or_exception(self):
        self.source.write_bytes(PRIVATE.encode())
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertNotEqual(inventory.main(["initialize"]), 0)
        self.assertFalse(self.destination.exists())
        self.assertNotIn(PRIVATE, out.getvalue() + err.getvalue())
        self.assertNotIn(str(self.source), out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
