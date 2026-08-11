"""Unit test modul whitelist (app/whitelist.py) — urllib dimock, tanpa bridge."""
import json
import urllib.request

import app.whitelist as whitelist


class _FakeResp:
    def __init__(self, data: dict):
        self._data = json.dumps(data).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(payload: dict):
    def urlopen(req, timeout=10):
        captured = req
        whitelist._last_req = captured  # untuk diinspeksi test
        whitelist._last_payload = json.loads(captured.data)
        assert captured.get_method() == "POST"
        return _FakeResp(payload)

    return urlopen


def test_add_mengirim_action_dan_nomor(tmp_env, monkeypatch):
    monkeypatch.setattr(whitelist, "_call", lambda a, n: {"ok": True, "allowed": [n]})
    r = whitelist.wa_whitelist_add("628123456789")
    assert r["ok"] is True
    assert "628123456789" in r["allowed"]


def test_remove_mengirim_action_dan_nomor(tmp_env, monkeypatch):
    captured = {}

    def fake_call(action, number):
        captured["action"] = action
        captured["number"] = number
        return {"ok": True, "allowed": ["6280000000000"]}

    monkeypatch.setattr(whitelist, "_call", fake_call)
    whitelist.wa_whitelist_remove("628123456789")
    assert captured["action"] == "remove"
    assert captured["number"] == "628123456789"


def test_list_payload_ke_bridge(tmp_env, monkeypatch):
    resp = {"ok": True, "allowed": ["6280000000000", "6281111111111"]}
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen(resp))
    r = whitelist.wa_whitelist_list()
    assert r["ok"] is True
    assert len(r["allowed"]) == 2
    # payload harus berisi action=list & header secret
    assert whitelist._last_payload["action"] == "list"
    assert whitelist._last_payload.get("number") is None
    headers = {k.lower(): v for k, v in whitelist._last_req.headers.items()}
    assert headers["x-secret"]


def test_bridge_gagal_dikembalikan_tanpa_raise(tmp_env, monkeypatch):
    def boom(req, timeout=10):
        raise OSError("koneksi ditolak")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    r = whitelist.wa_whitelist_list()
    assert r["ok"] is False
    assert "bridge tidak merespons" in r["error"]
