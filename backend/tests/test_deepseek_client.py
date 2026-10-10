import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import load_local_env
from app.deepseek_client import DeepSeekError, connection_status, test_connection


class FakeResponse:
    def __init__(self, status=200, data=None):
        self.status = status
        self.data = data if data is not None else {
            "model": "deepseek-flash",
            "choices": [{"message": {"content": "CONNECTED"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
        }

    def read(self, limit):
        return json.dumps(self.data).encode("utf-8")


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.request_data = None
        self.closed = False

    def request(self, method, path, body, headers):
        self.request_data = (method, path, body, headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class DeepSeekClientTests(unittest.TestCase):
    def test_status_never_returns_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret-value", "DEEPSEEK_MODEL": "deepseek-flash"}, clear=False):
            status = connection_status()
        self.assertTrue(status["configured"])
        self.assertFalse(status["key_exposed"])
        self.assertNotIn("secret-value", json.dumps(status))

    def test_connection_uses_fixed_host_and_returns_only_safe_summary(self):
        connection = FakeConnection(FakeResponse())
        seen = []
        def factory(host, timeout):
            seen.append((host, timeout))
            return connection
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret-value", "DEEPSEEK_MODEL": "deepseek-flash"}, clear=False):
            result = test_connection(connection_factory=factory)
        self.assertEqual(seen, [("api.deepseek.com", 30)])
        method, path, body, headers = connection.request_data
        self.assertEqual((method, path), ("POST", "/chat/completions"))
        self.assertEqual(headers["Authorization"], "Bearer secret-value")
        self.assertNotIn(b"secret-value", body)
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["usage"]["total_tokens"], 17)
        self.assertNotIn("secret-value", json.dumps(result))
        self.assertTrue(connection.closed)

    def test_missing_key_makes_no_connection(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "", "DEEPSEEK_MODEL": "deepseek-flash"}, clear=False):
            with self.assertRaises(DeepSeekError) as caught:
                test_connection(connection_factory=lambda *_: self.fail("network must not be used"))
        self.assertEqual(caught.exception.code, "not_configured")
        self.assertEqual(caught.exception.status_code, 400)

    def test_provider_errors_are_safe_and_not_retried(self):
        connection = FakeConnection(FakeResponse(401, {"error": {"message": "provider detail containing secret-value"}}))
        calls = []
        def factory(*args):
            calls.append(args)
            return connection
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret-value", "DEEPSEEK_MODEL": "deepseek-flash"}, clear=False):
            with self.assertRaises(DeepSeekError) as caught:
                test_connection(connection_factory=factory)
        self.assertEqual(caught.exception.code, "authentication_failed")
        self.assertNotIn("secret-value", str(caught.exception))
        self.assertEqual(len(calls), 1)

    def test_unexpected_confirmation_is_rejected(self):
        response = FakeResponse(data={"choices": [{"message": {"content": "something else"}}]})
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret-value", "DEEPSEEK_MODEL": "deepseek-flash"}, clear=False):
            with self.assertRaises(DeepSeekError) as caught:
                test_connection(connection_factory=lambda *_: FakeConnection(response))
        self.assertEqual(caught.exception.code, "unexpected_response")

    def test_env_file_is_allow_listed_and_process_environment_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("DEEPSEEK_API_KEY=file-key\nDEEPSEEK_MODEL=deepseek-flash\nUNRELATED_OPTION=must-not-change\n", encoding="utf-8")
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "process-key"}, clear=True):
                self.assertIsNone(load_local_env(path))
                self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "process-key")
                self.assertEqual(os.environ["DEEPSEEK_MODEL"], "deepseek-flash")
                self.assertNotIn("UNRELATED_OPTION", os.environ)


if __name__ == "__main__":
    unittest.main()
