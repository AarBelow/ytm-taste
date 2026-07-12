# tests/test_main.py
from fastapi.testclient import TestClient

from ytm_taste import google_oauth, main, youtube_client


def test_read_root():
    client = TestClient(main.app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ytm-taste"}


def test_login_redirects_to_google_and_stores_state(monkeypatch):
    monkeypatch.setattr(google_oauth, "build_flow", lambda *a, **kw: object())
    monkeypatch.setattr(
        google_oauth,
        "get_authorization_url",
        lambda flow: ("https://accounts.google.com/fake-auth-url", "fake-state"),
    )
    client = TestClient(main.app, follow_redirects=False)
    response = client.get("/login")
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "https://accounts.google.com/fake-auth-url"


def test_auth_callback_rejects_mismatched_state(monkeypatch):
    monkeypatch.setattr(google_oauth, "build_flow", lambda *a, **kw: object())
    monkeypatch.setattr(
        google_oauth,
        "get_authorization_url",
        lambda flow: ("https://accounts.google.com/fake-auth-url", "expected-state"),
    )
    client = TestClient(main.app, follow_redirects=False)
    client.get("/login")

    response = client.get("/auth/callback", params={"state": "wrong-state", "code": "abc"})
    assert response.status_code == 400


class FakeCredentials:
    def to_json(self):
        return '{"token": "fake"}'


def test_auth_callback_creates_user_and_triggers_sync(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(google_oauth, "build_flow", lambda *a, **kw: object())
    monkeypatch.setattr(
        google_oauth,
        "get_authorization_url",
        lambda flow: ("https://accounts.google.com/fake-auth-url", "expected-state"),
    )
    monkeypatch.setattr(google_oauth, "fetch_credentials", lambda flow, url: FakeCredentials())
    monkeypatch.setattr(youtube_client, "build_youtube_client", lambda credentials: object())
    monkeypatch.setattr(youtube_client, "get_channel_id", lambda youtube: "UC123")

    calls = []

    def fake_run_sync(db_path, user_id, youtube, **kwargs):
        calls.append((db_path, user_id))
        return {"liked_videos": 0, "playlists": 0, "subscriptions": 0, "elapsed_seconds": 0.0}

    monkeypatch.setattr(main.sync, "run_sync", fake_run_sync)

    client = TestClient(main.app, follow_redirects=False)
    client.get("/login")

    response = client.get("/auth/callback", params={"state": "expected-state", "code": "abc"})
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/"
    assert len(calls) == 1
    assert calls[0][0] == str(tmp_path / "test.db")

    from ytm_taste import db as db_module

    conn = db_module.get_connection(str(tmp_path / "test.db"))
    row = conn.execute("SELECT channel_id FROM users").fetchone()
    assert row == ("UC123",)


def test_auth_callback_without_channel_does_not_create_user(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(google_oauth, "build_flow", lambda *a, **kw: object())
    monkeypatch.setattr(
        google_oauth,
        "get_authorization_url",
        lambda flow: ("https://accounts.google.com/fake-auth-url", "expected-state"),
    )
    monkeypatch.setattr(google_oauth, "fetch_credentials", lambda flow, url: FakeCredentials())
    monkeypatch.setattr(youtube_client, "build_youtube_client", lambda credentials: object())
    monkeypatch.setattr(youtube_client, "get_channel_id", lambda youtube: None)

    client = TestClient(main.app, follow_redirects=False)
    client.get("/login")

    response = client.get("/auth/callback", params={"state": "expected-state", "code": "abc"})
    assert response.status_code == 400
