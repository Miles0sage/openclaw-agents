"""Unit tests for cli/openclaw_cli.py."""

import io
import json
import os
import re
import sys
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from cli import openclaw_cli as cli


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class TestOpenClawCLI(unittest.TestCase):
    def _mock_response(self, payload):
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        response = MagicMock()
        response.read.return_value = payload.encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def _http_error(self, code=404, payload=None):
        if payload is None:
            payload = {"error": "not found"}
        if not isinstance(payload, str):
            payload = json.dumps(payload)
        return urllib.error.HTTPError(
            url="http://localhost:18789/health",
            code=code,
            msg="error",
            hdrs=None,
            fp=io.BytesIO(payload.encode("utf-8")),
        )

    def _run_main(self, argv, env=None):
        out = io.StringIO()
        err = io.StringIO()
        with patch.object(sys, "argv", ["openclaw"] + argv), patch.dict(
            os.environ, env or {}, clear=True
        ), redirect_stdout(out), redirect_stderr(err):
            rc = cli.main()
        return rc, out.getvalue(), err.getvalue()

    def _strip_ansi(self, text):
        return ANSI_RE.sub("", text)

    def _headers(self, request):
        return {k.lower(): v for k, v in request.header_items()}

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_health_success_returns_zero_and_prints_healthy(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response({"status": "operational"})
        rc, out, _ = self._run_main(["health"])

        clean = self._strip_ansi(out)
        self.assertEqual(rc, 0)
        self.assertIn("Gateway healthy", clean)
        self.assertIn("operational", clean)

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_health_json_returns_raw_json(self, mock_urlopen):
        payload = {"status": "operational", "uptime": 123}
        mock_urlopen.return_value = self._mock_response(payload)
        rc, out, _ = self._run_main(["health", "--json"])

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), payload)

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_run_prompt_posts_to_api_jobs_and_prints_job_id(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response({"job_id": "job-123"})
        env = {"OPENCLAW_AUTH_TOKEN": "tok-1"}
        rc, out, _ = self._run_main(["run", "build website"], env=env)

        clean = self._strip_ansi(out)
        self.assertEqual(rc, 0)
        self.assertIn("job-123", clean)
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "http://localhost:18789/api/jobs")
        self.assertEqual(json.loads(request.data.decode("utf-8")), {"prompt": "build website"})
        self.assertEqual(self._headers(request).get("x-auth-token"), "tok-1")

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_run_json_prints_raw_json(self, mock_urlopen):
        payload = {"job_id": "job-456", "status": "queued"}
        mock_urlopen.return_value = self._mock_response(payload)
        env = {"OPENCLAW_AUTH_TOKEN": "tok-2"}
        rc, out, _ = self._run_main(["run", "do thing", "--json"], env=env)

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), payload)

    def test_run_without_prompt_exits_with_error(self):
        out = io.StringIO()
        err = io.StringIO()
        with patch.object(sys, "argv", ["openclaw", "run"]), patch.dict(
            os.environ, {}, clear=True
        ), redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            cli.main()
        self.assertNotEqual(ctx.exception.code, 0)

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_status_gets_job_by_id(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response({"job_id": "abc-1", "status": "running"})
        env = {"OPENCLAW_AUTH_TOKEN": "tok-3"}
        rc, out, _ = self._run_main(["status", "abc-1"], env=env)

        clean = self._strip_ansi(out)
        self.assertEqual(rc, 0)
        self.assertIn("Job:", clean)
        self.assertIn("abc-1", clean)
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "http://localhost:18789/api/jobs/abc-1")

    def test_status_without_job_id_exits_with_error(self):
        out = io.StringIO()
        err = io.StringIO()
        with patch.object(sys, "argv", ["openclaw", "status"]), patch.dict(
            os.environ, {}, clear=True
        ), redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            cli.main()
        self.assertNotEqual(ctx.exception.code, 0)

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_jobs_gets_default_limit_20(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response([{"job_id": "j1", "status": "queued"}])
        env = {"OPENCLAW_AUTH_TOKEN": "tok-4"}
        rc, out, _ = self._run_main(["jobs"], env=env)

        clean = self._strip_ansi(out)
        self.assertEqual(rc, 0)
        self.assertIn("Recent jobs: 1", clean)
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "http://localhost:18789/api/jobs?limit=20")

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_jobs_json_prints_raw_json(self, mock_urlopen):
        payload = {"jobs": [{"job_id": "j1", "status": "done"}]}
        mock_urlopen.return_value = self._mock_response(payload)
        env = {"OPENCLAW_AUTH_TOKEN": "tok-5"}
        rc, out, _ = self._run_main(["jobs", "--json"], env=env)

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), payload)

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_missing_auth_token_for_run_exits_one(self, mock_urlopen):
        rc, out, _ = self._run_main(["run", "hello"], env={})

        clean = self._strip_ansi(out)
        self.assertEqual(rc, 1)
        self.assertIn("OPENCLAW_AUTH_TOKEN is required", clean)
        mock_urlopen.assert_not_called()

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_missing_auth_token_for_status_exits_one(self, mock_urlopen):
        rc, out, _ = self._run_main(["status", "job-x"], env={})

        clean = self._strip_ansi(out)
        self.assertEqual(rc, 1)
        self.assertIn("OPENCLAW_AUTH_TOKEN is required", clean)
        mock_urlopen.assert_not_called()

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_missing_auth_token_for_jobs_exits_one(self, mock_urlopen):
        rc, out, _ = self._run_main(["jobs"], env={})

        clean = self._strip_ansi(out)
        self.assertEqual(rc, 1)
        self.assertIn("OPENCLAW_AUTH_TOKEN is required", clean)
        mock_urlopen.assert_not_called()

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_health_does_not_require_auth_token(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response({"status": "ok"})
        rc, out, _ = self._run_main(["health"], env={})

        clean = self._strip_ansi(out)
        self.assertEqual(rc, 0)
        self.assertIn("Gateway healthy", clean)
        request = mock_urlopen.call_args[0][0]
        self.assertNotIn("x-auth-token", self._headers(request))

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_gateway_url_env_changes_base_url(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response({"status": "ok"})
        env = {"OPENCLAW_GATEWAY_URL": "https://gateway.example.com/"}
        rc, _, _ = self._run_main(["health"], env=env)

        self.assertEqual(rc, 0)
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.full_url, "https://gateway.example.com/health")

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_http_error_404_exits_one_and_prints_error(self, mock_urlopen):
        mock_urlopen.side_effect = self._http_error(404, {"error": "missing route"})
        rc, out, _ = self._run_main(["health"], env={})

        clean = self._strip_ansi(out)
        self.assertEqual(rc, 1)
        self.assertIn("HTTP 404", clean)
        self.assertIn("missing route", clean)

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_connection_error_exits_one_and_prints_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        rc, out, _ = self._run_main(["health"], env={})

        clean = self._strip_ansi(out)
        self.assertEqual(rc, 1)
        self.assertIn("Connection failed", clean)

    @patch("cli.openclaw_cli.time.sleep", return_value=None)
    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_run_wait_polls_until_terminal_status(self, mock_urlopen, _mock_sleep):
        mock_urlopen.side_effect = [
            self._mock_response({"job_id": "job-77", "status": "queued"}),
            self._mock_response({"job_id": "job-77", "status": "running"}),
            self._mock_response({"job_id": "job-77", "status": "done"}),
        ]
        env = {"OPENCLAW_AUTH_TOKEN": "tok-6"}
        rc, out, _ = self._run_main(["run", "wait for complete", "--wait"], env=env)

        clean = self._strip_ansi(out)
        self.assertEqual(rc, 0)
        self.assertIn("Final status:", clean)
        self.assertEqual(mock_urlopen.call_count, 3)

    @patch("cli.openclaw_cli.urllib.request.urlopen")
    def test_status_failed_returns_exit_one(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response({"job_id": "job-f", "status": "failed", "error": "boom"})
        env = {"OPENCLAW_AUTH_TOKEN": "tok-7"}
        rc, out, _ = self._run_main(["status", "job-f"], env=env)

        clean = self._strip_ansi(out)
        self.assertEqual(rc, 1)
        self.assertIn("failed", clean.lower())
        self.assertIn("boom", clean)


if __name__ == "__main__":
    unittest.main()
