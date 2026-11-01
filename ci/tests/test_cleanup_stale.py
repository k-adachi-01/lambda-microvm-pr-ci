"""Regression tests for the orphan sweeper's timestamp handling.

list-microvms returns ``startedAt`` (not ``createdAt``). The original sweeper
read ``createdAt``, got None for every VM, and therefore never terminated
anything. Keep the normalisation tested so that cannot regress silently.
"""
import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_stale.py"
spec = importlib.util.spec_from_file_location("cleanup_stale", SCRIPT)
cleanup_stale = importlib.util.module_from_spec(spec)
sys.modules["cleanup_stale"] = cleanup_stale
spec.loader.exec_module(cleanup_stale)


class ParseTimeTests(unittest.TestCase):
    def test_none_stays_none(self):
        self.assertIsNone(cleanup_stale.parse_time(None))

    def test_datetime_passes_through(self):
        value = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.assertEqual(cleanup_stale.parse_time(value), value)

    def test_iso_string_is_parsed(self):
        parsed = cleanup_stale.parse_time("2026-11-01T21:08:04+09:00")
        self.assertEqual(parsed.isoformat(), "2026-11-01T21:08:04+09:00")

    def test_epoch_seconds_are_parsed(self):
        parsed = cleanup_stale.parse_time(0)
        self.assertEqual(parsed, datetime(1970, 1, 1, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
