import importlib.util
import sys
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "notify_wecom.py"
spec = importlib.util.spec_from_file_location("notify_wecom", SCRIPT)
nw = importlib.util.module_from_spec(spec)
sys.modules["notify_wecom"] = nw
spec.loader.exec_module(nw)


def test_empty_webhook_skips():
    assert nw.send_wecom("", "hi") is False
    assert nw.send_wecom(None, "hi") is False


def test_posts_to_webhook():
    with mock.patch("urllib.request.urlopen") as u:
        resp = mock.Mock()
        resp.read.return_value = b'{"errcode":0}'
        u.return_value.__enter__.return_value = resp
        ok = nw.send_wecom("abc123", "hello")
    assert ok is True
    args, _ = u.call_args
    body = args[0].data
    assert b"hello" in body


def test_error_returns_false():
    with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
        assert nw.send_wecom("abc", "hi") is False
