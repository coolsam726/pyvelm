"""Syncable schema diff detection for Apps catalog."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm.db_autogen import Diff, SchemaAlteration, diff_has_syncable_changes


class SyncableDiffTests(unittest.TestCase):
    def test_orphan_columns_are_not_syncable(self):
        env = MagicMock()
        diff = Diff(orphan_columns=[("res_partner", "legacy_col")])
        self.assertFalse(diff_has_syncable_changes(env, diff))

    def test_type_mismatch_is_not_syncable(self):
        env = MagicMock()
        diff = Diff(
            alterations=[
                SchemaAlteration(
                    "res_partner",
                    "age",
                    "type",
                    "model 'integer', DB 'text'",
                )
            ]
        )
        self.assertFalse(diff_has_syncable_changes(env, diff))

    def test_new_column_is_syncable(self):
        env = MagicMock()
        diff = Diff(new_columns=[("res_partner", "note", MagicMock(), False, "text")])
        self.assertTrue(diff_has_syncable_changes(env, diff))

    def test_drop_not_null_is_syncable(self):
        env = MagicMock()
        diff = Diff(
            alterations=[
                SchemaAlteration(
                    "res_partner",
                    "name",
                    "drop_not_null",
                    "ALTER COLUMN DROP NOT NULL",
                )
            ]
        )
        with patch("pyvelm.database._conn_capabilities") as cap:
            cap.return_value.name = "postgresql"
            self.assertTrue(diff_has_syncable_changes(env, diff))

    def test_nullability_not_syncable_on_sqlite(self):
        env = MagicMock()
        diff = Diff(
            alterations=[
                SchemaAlteration(
                    "res_partner",
                    "name",
                    "drop_not_null",
                    "ALTER COLUMN DROP NOT NULL",
                )
            ]
        )
        with patch("pyvelm.database._conn_capabilities") as cap:
            cap.return_value.name = "sqlite"
            self.assertFalse(diff_has_syncable_changes(env, diff))

    def test_set_not_null_with_null_rows_is_not_syncable(self):
        env = MagicMock()
        diff = Diff(
            alterations=[
                SchemaAlteration(
                    "res_partner",
                    "code",
                    "set_not_null",
                    "backfill NULLs, then SET NOT NULL",
                )
            ]
        )
        with patch("pyvelm.db_autogen._column_has_nulls", return_value=True):
            self.assertFalse(diff_has_syncable_changes(env, diff))

    def test_set_not_null_without_null_rows_is_syncable(self):
        env = MagicMock()
        diff = Diff(
            alterations=[
                SchemaAlteration(
                    "res_partner",
                    "code",
                    "set_not_null",
                    "backfill NULLs, then SET NOT NULL",
                )
            ]
        )
        with patch("pyvelm.db_autogen._column_has_nulls", return_value=False):
            self.assertTrue(diff_has_syncable_changes(env, diff))


if __name__ == "__main__":
    unittest.main()
