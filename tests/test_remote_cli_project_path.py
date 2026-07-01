import json
import os
from types import SimpleNamespace

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "geocentric-code-client.py"
spec = importlib.util.spec_from_file_location("geocentric_code_client", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeResponse:
    headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b'{"reply": "ok"}'


def test_remote_cli_sends_current_project_path(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=30):
        captured["req"] = req
        return FakeResponse()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)

    cli = module.RemoteCLI("http://example.test")
    cli.stream_chat("hello")

    payload = json.loads(captured["req"].data.decode("utf-8"))
    assert payload["projectPath"] == os.getcwd()
