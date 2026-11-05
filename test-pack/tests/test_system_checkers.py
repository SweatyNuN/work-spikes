from __future__ import annotations

import urllib.error

from testpack.checkers import system


class StubContext:
    default_timeout = 5


class FakeResponse:
    def __init__(self, status: int):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_http_blocked_passes_on_network_failure(monkeypatch):
    def blocked(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(system.urllib.request, "urlopen", blocked)
    outcome = system.http_blocked(StubContext(), {"urls": ["https://example.com"]})

    assert outcome.status == "pass"
    assert "blocked" in outcome.message.lower()


def test_http_blocked_passes_on_blocked_status(monkeypatch):
    def forbidden(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", None, None)

    monkeypatch.setattr(system.urllib.request, "urlopen", forbidden)
    outcome = system.http_blocked(StubContext(), {"urls": ["https://example.com"]})

    assert outcome.status == "pass"
    assert "HTTP 403" in outcome.detail


def test_http_blocked_fails_when_reachable(monkeypatch):
    monkeypatch.setattr(
        system.urllib.request,
        "urlopen",
        lambda request, timeout=None: FakeResponse(200),
    )
    outcome = system.http_blocked(StubContext(), {"urls": ["https://example.com"]})

    assert outcome.status == "fail"
    assert "reachable" in outcome.message


def test_http_blocked_fails_on_unexpected_status(monkeypatch):
    def server_error(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 500, "Server Error", None, None)

    monkeypatch.setattr(system.urllib.request, "urlopen", server_error)
    outcome = system.http_blocked(StubContext(), {"urls": ["https://example.com"]})

    assert outcome.status == "fail"


def test_http_blocked_requires_urls():
    outcome = system.http_blocked(StubContext(), {})

    assert outcome.status == "fail"
    assert "url" in outcome.message


def test_http_blocked_all_urls_must_be_blocked(monkeypatch):
    calls = {"count": 0}

    def mixed(request, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.URLError("blocked")
        return FakeResponse(200)

    monkeypatch.setattr(system.urllib.request, "urlopen", mixed)
    outcome = system.http_blocked(
        StubContext(),
        {"urls": ["https://blocked.example", "https://reachable.example"]},
    )

    assert outcome.status == "fail"
    assert "1 of 2" in outcome.message
