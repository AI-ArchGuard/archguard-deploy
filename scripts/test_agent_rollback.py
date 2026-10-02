import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("rollback", Path(__file__).with_name("verify-agent-rollback.py"))
rollback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollback)


class HistoricalSnapshotTest(unittest.TestCase):
    def test_stage_three_callback_has_no_agent_revision_but_new_revision_is_preserved(self):
        self.assertIsNone(rollback.governance.callback_revision({"externalId": "7"}))
        self.assertEqual(rollback.governance.callback_revision({"currentHeadRevisionId": "synthetic-revision"}), "synthetic-revision")

    def test_accepts_identical_all_table_snapshots(self):
        snapshot = {table: {"rows": 2, "digest": "a" * 32} for table in rollback.TABLES}
        rollback.assert_unchanged(snapshot, copy.deepcopy(snapshot))

    def test_rejects_missing_tables_deleted_rows_and_modified_content(self):
        before = {table: {"rows": 2, "digest": "a" * 32} for table in rollback.TABLES}
        for table in rollback.TABLES:
            for change in ("missing", "rows", "digest"):
                after = copy.deepcopy(before)
                if change == "missing":
                    del after[table]
                elif change == "rows":
                    after[table]["rows"] = 1
                else:
                    after[table]["digest"] = "b" * 32
                with self.subTest(table=table, change=change), self.assertRaises(AssertionError):
                    rollback.assert_unchanged(before, after)
