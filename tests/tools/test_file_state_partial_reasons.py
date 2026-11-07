"""tests for specific partial read reasons in file_state check_stale.

verifies that write_file staleness refusals name the exact condition
(unstable read, redacted content, truncated lines, character budget,
or pagination) instead of always claiming offset/limit pagination.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools import file_state
from tools.file_tools import clear_file_ops_cache, read_file_tool, write_file_tool
from tools.file_tools_read_tracking import reset_file_dedup


class FileStatePartialReasonUnitTests(unittest.TestCase):
    """unit tests for record_read and check_stale reason formatting."""

    def setUp(self) -> None:
        file_state.get_registry().clear()
        self._tmpdir = tempfile.mkdtemp(prefix="hermes_reason_unit_")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        file_state.get_registry().clear()

    def _mk(self, name: str = "test.txt", content: str = "hello\n") -> str:
        p = os.path.join(self._tmpdir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_unstable_read_reason(self) -> None:
        p = self._mk()
        file_state.record_read("task1", p, partial=True, reason="unstable read")
        warn = file_state.check_stale("task1", p)
        self.assertIsNotNone(warn)
        assert warn is not None
        self.assertIn("unstable read", warn)
        self.assertIn("re-read the file, or use patch", warn)
        self.assertNotIn("offset/limit pagination", warn)

    def test_redacted_content_reason(self) -> None:
        p = self._mk()
        file_state.record_read("task1", p, partial=True, reason="redacted content")
        warn = file_state.check_stale("task1", p)
        self.assertIsNotNone(warn)
        assert warn is not None
        self.assertIn("redacted content", warn)
        self.assertIn("avoid overwriting redacted files", warn)
        self.assertNotIn("offset/limit pagination", warn)

    def test_truncated_lines_reason(self) -> None:
        p = self._mk()
        file_state.record_read("task1", p, partial=True, reason="truncated lines")
        warn = file_state.check_stale("task1", p)
        self.assertIsNotNone(warn)
        assert warn is not None
        self.assertIn("truncated lines", warn)
        self.assertIn("lines clamped to the line-length limit", warn)
        self.assertNotIn("offset/limit pagination", warn)

    def test_character_budget_reason(self) -> None:
        p = self._mk()
        file_state.record_read("task1", p, partial=True, reason="character budget")
        warn = file_state.check_stale("task1", p)
        self.assertIsNotNone(warn)
        assert warn is not None
        self.assertIn("character budget", warn)
        self.assertIn("output cut off by the character budget", warn)
        self.assertNotIn("offset/limit pagination", warn)

    def test_pagination_reason(self) -> None:
        p = self._mk()
        file_state.record_read("task1", p, partial=True, reason="pagination")
        warn = file_state.check_stale("task1", p)
        self.assertIsNotNone(warn)
        assert warn is not None
        self.assertIn("offset/limit pagination", warn)
        self.assertIn("read the remaining pages, or use patch", warn)

    def test_default_partial_reason_falls_back_to_pagination(self) -> None:
        p = self._mk()
        file_state.record_read("task1", p, partial=True)
        warn = file_state.check_stale("task1", p)
        self.assertIsNotNone(warn)
        assert warn is not None
        self.assertIn("offset/limit pagination", warn)


class FileToolsPartialReasonIntegrationTests(unittest.TestCase):
    """integration tests through read_file_tool and write_file_tool."""

    def setUp(self) -> None:
        file_state.get_registry().clear()
        self._tmpdir = tempfile.mkdtemp(prefix="hermes_reason_int_")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        file_state.get_registry().clear()
        clear_file_ops_cache("test_agent")
        reset_file_dedup("test_agent")

    def _write_file(self, name: str, content: str) -> str:
        p = os.path.join(self._tmpdir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_pagination_refusal_mentions_pagination(self) -> None:
        p = self._write_file("paged.txt", "line 1\nline 2\nline 3\nline 4\n")
        r = json.loads(read_file_tool(path=p, offset=1, limit=2, task_id="test_agent"))
        self.assertNotIn("error", r)

        w = json.loads(write_file_tool(path=p, content="new content\n", task_id="test_agent"))
        self.assertTrue(w.get("stale_write_blocked"), w)
        err = w.get("error", "")
        self.assertIn("offset/limit pagination", err)
        self.assertIn("read the remaining pages, or use patch", err)

    def test_redacted_content_refusal_mentions_redaction(self) -> None:
        secret = "sk-ant-api03-" + "a" * 90
        p = self._write_file("api_token.txt", f"token = {secret}\n")
        r = json.loads(read_file_tool(path=p, task_id="test_agent"))
        self.assertNotIn("error", r)

        w = json.loads(write_file_tool(path=p, content="new content\n", task_id="test_agent"))
        self.assertTrue(w.get("stale_write_blocked"), w)
        err = w.get("error", "")
        self.assertIn("redacted content", err)
        self.assertIn("avoid overwriting redacted files", err)
        self.assertNotIn("offset/limit pagination", err)

    def test_truncated_lines_refusal_mentions_truncated_lines(self) -> None:
        long_line = "a" * 2500
        p = self._write_file("long_lines.txt", f"{long_line}\nline 2\n")
        r = json.loads(read_file_tool(path=p, task_id="test_agent"))
        self.assertNotIn("error", r)

        w = json.loads(write_file_tool(path=p, content="new content\n", task_id="test_agent"))
        self.assertTrue(w.get("stale_write_blocked"), w)
        err = w.get("error", "")
        self.assertIn("truncated lines", err)
        self.assertIn("lines clamped to the line-length limit", err)
        self.assertNotIn("offset/limit pagination", err)

    def test_character_budget_refusal_mentions_char_budget(self) -> None:
        lines = [f"item {i:03d}\n" for i in range(100)]
        p = self._write_file("budget.txt", "".join(lines))
        with patch("tools.file_tools._get_max_read_chars", return_value=120):
            r = json.loads(read_file_tool(path=p, task_id="test_agent"))
            self.assertNotIn("error", r)
            self.assertTrue(r.get("truncated"))
            self.assertEqual(r.get("truncated_by"), "bytes")

        w = json.loads(write_file_tool(path=p, content="new content\n", task_id="test_agent"))
        self.assertTrue(w.get("stale_write_blocked"), w)
        err = w.get("error", "")
        self.assertIn("character budget", err)
        self.assertIn("output cut off by the character budget", err)
        self.assertNotIn("offset/limit pagination", err)

    def test_unstable_read_refusal_mentions_unstable_read(self) -> None:
        p = self._write_file("unstable.txt", "line 1\nline 2\nline 3\n")
        from tools import file_tools

        real_metadata = file_tools._file_metadata
        calls = 0

        def flaky_metadata(path_str):
            nonlocal calls
            calls += 1
            meta = real_metadata(path_str)
            if calls >= 2 and meta is not None:
                # simulate mtime / size changing during the read
                return (meta[0] + 10.0, meta[1] + 10)
            return meta

        with patch("tools.file_tools._file_metadata", side_effect=flaky_metadata):
            r = json.loads(read_file_tool(path=p, task_id="test_agent"))
            self.assertNotIn("error", r)

        w = json.loads(write_file_tool(path=p, content="new content\n", task_id="test_agent"))
        self.assertTrue(w.get("stale_write_blocked"), w)
        err = w.get("error", "")
        self.assertIn("unstable read", err)
        self.assertIn("re-read the file, or use patch", err)
        self.assertNotIn("offset/limit pagination", err)

    def test_paged_read_with_earlier_truncated_lines_blocks_overwrite(self) -> None:
        long_line = "a" * 2500
        content = f"{long_line}\nsecond line\nthird line\n"
        p = self._write_file("paged_truncated.txt", content)
        # page 1 has the clamped line
        r1 = json.loads(read_file_tool(path=p, offset=1, limit=1, task_id="test_agent"))
        self.assertNotIn("error", r1)
        self.assertTrue(r1.get("truncated_lines"))
        # intermediate check: reason should be truncated lines, not pagination
        w_mid = json.loads(write_file_tool(path=p, content="new content\n", task_id="test_agent"))
        self.assertTrue(w_mid.get("stale_write_blocked"), w_mid)
        self.assertIn("truncated lines", w_mid.get("error", ""))
        self.assertNotIn("offset/limit pagination", w_mid.get("error", ""))
        # page 2 is clean
        r2 = json.loads(read_file_tool(path=p, offset=2, limit=2, task_id="test_agent"))
        self.assertNotIn("error", r2)
        # all lines 1..3 have been covered, but page 1 had truncated lines: write must still be refused
        w = json.loads(write_file_tool(path=p, content="new content\n", task_id="test_agent"))
        self.assertTrue(w.get("stale_write_blocked"), w)
        err = w.get("error", "")
        self.assertIn("truncated lines", err)
        self.assertIn("lines clamped to the line-length limit", err)
        self.assertNotIn("offset/limit pagination", err)

    def test_paged_read_with_earlier_redaction_blocks_overwrite(self) -> None:
        secret = "sk-ant-api03-" + "a" * 90
        content = f"token = {secret}\nsecond line\nthird line\n"
        p = self._write_file("paged_secret.txt", content)
        # page 1 has secret token
        r1 = json.loads(read_file_tool(path=p, offset=1, limit=1, task_id="test_agent"))
        self.assertNotIn("error", r1)
        # intermediate check
        w_mid = json.loads(write_file_tool(path=p, content="new content\n", task_id="test_agent"))
        self.assertTrue(w_mid.get("stale_write_blocked"), w_mid)
        self.assertIn("redacted content", w_mid.get("error", ""))
        self.assertNotIn("offset/limit pagination", w_mid.get("error", ""))
        # page 2 is clean
        r2 = json.loads(read_file_tool(path=p, offset=2, limit=2, task_id="test_agent"))
        self.assertNotIn("error", r2)
        # all lines 1..3 covered, but page 1 was redacted: write must still be refused
        w = json.loads(write_file_tool(path=p, content="new content\n", task_id="test_agent"))
        self.assertTrue(w.get("stale_write_blocked"), w)
        err = w.get("error", "")
        self.assertIn("redacted content", err)
        self.assertIn("avoid overwriting redacted files", err)
        self.assertNotIn("offset/limit pagination", err)

    def test_complete_clean_read_allows_write(self) -> None:
        p = self._write_file("clean.txt", "line 1\nline 2\nline 3\n")
        r = json.loads(read_file_tool(path=p, task_id="test_agent"))
        self.assertNotIn("error", r)

        w = json.loads(write_file_tool(path=p, content="updated content\n", task_id="test_agent"))
        self.assertFalse(w.get("stale_write_blocked", False))
        self.assertNotIn("error", w)
        with open(p, encoding="utf-8") as f:
            self.assertEqual(f.read(), "updated content\n")


if __name__ == "__main__":
    unittest.main()
