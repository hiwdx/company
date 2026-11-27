"""Offline safety/diagnostic regressions; never proof of provider capability."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("probe", ROOT / "scripts/probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_zero_failures_is_not_error(self):
        fixture = (ROOT / "tests/fixtures/cli-schema.txt").read_text()
        result = probe.inspect_cli(fixture, "finance")
        self.assertFalse(result["has_error_marker"])
        self.assertEqual(result["period_metadata"][0]["DisclosureCurrency"], "TWD")
        self.assertNotIn("123.45", str(result))

    def test_multiline_content_cannot_become_schema(self):
        fixture = (ROOT / "tests/fixtures/cli-schema.txt").read_text()
        result = probe.inspect_cli(fixture, "profile")
        self.assertEqual(len(result["tables"]), 2)
        self.assertEqual(result["tables"][1]["columns"], ["code", "name", "introduction"])
        self.assertEqual({r["code"] for r in result["identities"]}, {"usDEMO", "hk00000", "hk00001"})
        self.assertNotIn("first line", str(result))

    def test_actual_error_remains_visible(self):
        for text in ("[Batch] 失败: 1", "Error: unavailable", "NOT_DISCLOSED"):
            self.assertTrue(probe.inspect_cli(text, "search")["has_error_marker"])

    def test_no_signed_urls_or_credentials_published(self):
        self.assertIsNone(probe.public_url("https://example.org/doc?token=secret"))
        self.assertIsNone(probe.public_url("https://user:secret@example.org/doc"))
        self.assertIsNone(probe.public_url("https://127.0.0.1/doc"))
        self.assertIsNone(probe.public_url("https://file.finance.qq.com/doc#token=secret"))
        # An HTTP mirror is recorded as evidence, not followed/upgraded to HTTPS.
        self.assertEqual(probe.inspect_cli("http://file.finance.qq.com/example.pdf", "detail")["public_urls"],
                         ["http://file.finance.qq.com/example.pdf"])

    @patch.object(probe.subprocess, "run")
    def test_nonsec_network_destinations_rejected_before_io(self, call):
        for url in ("http://data.sec.gov/file", "https://www.sec.gov.evil.org/file", "https://127.0.0.1/file",
                    "https://user@data.sec.gov/file", "https://data.sec.gov/file?target=evil"):
            with self.assertRaises(ValueError):
                probe.fetch(url, "truthful contact")
        call.assert_not_called()

    @patch("builtins.print")
    @patch.object(probe, "fetch")
    def test_host_denial_stops_sec_data_calls(self, fetch, _print):
        fetch.side_effect = [({"http_status": 403}, b""), ({"http_status": 403}, b"")]
        result = probe.sec("CompanyPhase0 (contact: https://github.com/hiwdx/company/issues/1)")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result["results"][-1]["status"], "skipped_after_host_denial")

    @patch("builtins.print")
    @patch.object(probe.time, "sleep")
    @patch.object(probe.subprocess, "run")
    def test_cli_denial_stops_later_queries(self, run, _sleep, _print):
        run.side_effect = [SimpleNamespace(stdout=b"westock 0.0.2", stderr=b"", returncode=0),
            SimpleNamespace(stdout=b"", stderr=b"HTTP 429: too many requests", returncode=1)]
        result = probe.westock(str(ROOT / "scripts/probe.py"))
        self.assertEqual(run.call_count, 2)
        self.assertTrue(result["results"][1]["stop_after_denial"])
        self.assertEqual(result["results"][-1]["status"], "skipped_after_auth_or_rate_limit")


if __name__ == "__main__":
    unittest.main()
