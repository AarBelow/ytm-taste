# tests/test_main.py
from fastapi.testclient import TestClient

from ytm_taste import google_oauth, main, youtube_client


def test_health_returns_status():
    client = TestClient(main.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ytm-taste"}


def test_login_redirects_to_google_and_stores_state(monkeypatch):
    monkeypatch.setattr(google_oauth, "build_flow", lambda *a, **kw: object())
    monkeypatch.setattr(
        google_oauth,
        "get_authorization_url",
        lambda flow: ("https://accounts.google.com/fake-auth-url", "fake-state", "fake-verifier"),
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
        lambda flow: (
            "https://accounts.google.com/fake-auth-url",
            "expected-state",
            "expected-verifier",
        ),
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
        lambda flow: (
            "https://accounts.google.com/fake-auth-url",
            "expected-state",
            "expected-verifier",
        ),
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


def test_auth_callback_reuses_code_verifier_from_login(monkeypatch, tmp_path):
    # Real bug, reproduced live against a real Google account: /login and
    # /auth/callback are two separate HTTP requests, so main.py builds two
    # separate Flow objects via _build_flow(). The Flow used in /login
    # auto-generates a PKCE code_verifier and sends the matching
    # code_challenge to Google. If the Flow built in /auth/callback doesn't
    # get seeded with that exact same code_verifier, Google rejects the
    # token exchange with "Missing code verifier" (InvalidGrantError). This
    # test verifies the fix: the code_verifier google_oauth.get_authorization_url
    # returns during /login must be the one google_oauth.build_flow is called
    # with during /auth/callback.
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "test.db"))

    build_flow_calls = []

    def fake_build_flow(client_id, client_secret, redirect_uri, code_verifier=None):
        build_flow_calls.append(code_verifier)
        return object()

    monkeypatch.setattr(google_oauth, "build_flow", fake_build_flow)
    monkeypatch.setattr(
        google_oauth,
        "get_authorization_url",
        lambda flow: (
            "https://accounts.google.com/fake-auth-url",
            "expected-state",
            "the-real-code-verifier",
        ),
    )
    monkeypatch.setattr(google_oauth, "fetch_credentials", lambda flow, url: FakeCredentials())
    monkeypatch.setattr(youtube_client, "build_youtube_client", lambda credentials: object())
    monkeypatch.setattr(youtube_client, "get_channel_id", lambda youtube: "UC123")
    monkeypatch.setattr(
        main.sync,
        "run_sync",
        lambda *a, **kw: {
            "liked_videos": 0,
            "playlists": 0,
            "subscriptions": 0,
            "elapsed_seconds": 0.0,
        },
    )

    client = TestClient(main.app, follow_redirects=False)
    client.get("/login")
    client.get("/auth/callback", params={"state": "expected-state", "code": "abc"})

    # First call is /login's Flow (no verifier yet, one gets autogenerated by
    # the real Flow in production). Second call is /auth/callback's Flow,
    # which must be built with the SAME verifier get_authorization_url
    # returned during /login -- not None, not a fresh one.
    assert build_flow_calls == [None, "the-real-code-verifier"]


def test_auth_callback_without_channel_does_not_create_user(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(google_oauth, "build_flow", lambda *a, **kw: object())
    monkeypatch.setattr(
        google_oauth,
        "get_authorization_url",
        lambda flow: (
            "https://accounts.google.com/fake-auth-url",
            "expected-state",
            "expected-verifier",
        ),
    )
    monkeypatch.setattr(google_oauth, "fetch_credentials", lambda flow, url: FakeCredentials())
    monkeypatch.setattr(youtube_client, "build_youtube_client", lambda credentials: object())
    monkeypatch.setattr(youtube_client, "get_channel_id", lambda youtube: None)

    client = TestClient(main.app, follow_redirects=False)
    client.get("/login")

    response = client.get("/auth/callback", params={"state": "expected-state", "code": "abc"})
    assert response.status_code == 400


def _complete_fake_login(client, monkeypatch, tmp_path, channel_id="UC123"):
    """Drive the real /login + /auth/callback flow with fakes so the client
    ends up with a valid signed session cookie carrying user_id, and returns
    the db path the app is using."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(main, "DB_PATH", db_path)
    monkeypatch.setattr(google_oauth, "build_flow", lambda *a, **kw: object())
    monkeypatch.setattr(
        google_oauth,
        "get_authorization_url",
        lambda flow: ("https://accounts.google.com/fake", "st", "vf"),
    )
    monkeypatch.setattr(google_oauth, "fetch_credentials", lambda flow, url: FakeCredentials())
    monkeypatch.setattr(youtube_client, "build_youtube_client", lambda credentials: object())
    monkeypatch.setattr(youtube_client, "get_channel_id", lambda youtube: channel_id)
    monkeypatch.setattr(
        main.sync,
        "run_sync",
        lambda *a, **kw: {
            "liked_videos": 0,
            "playlists": 0,
            "subscriptions": 0,
            "elapsed_seconds": 0.0,
        },
    )
    client.get("/login")
    client.get("/auth/callback", params={"state": "st", "code": "abc"})
    return db_path


def test_root_redirects_to_login_when_not_logged_in():
    client = TestClient(main.app, follow_redirects=False)
    response = client.get("/")
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/login"


def test_display_artist_strips_topic_suffix():
    assert main._display_artist("Jinwoo Jung - Topic") == "Jinwoo Jung"
    assert main._display_artist("Some Band") == "Some Band"
    # only a trailing suffix is stripped, not a mid-string occurrence
    assert main._display_artist("A - Topic B") == "A - Topic B"


def test_render_results_page_lists_artists_in_order():
    html_out = main.render_results_page([("Alpha", 5), ("Beta", 2)])
    assert "Alpha" in html_out
    assert "Beta" in html_out
    # highest count appears before lower count in the document
    assert html_out.index("Alpha") < html_out.index("Beta")
    assert "5" in html_out and "2" in html_out


def test_render_results_page_empty_state():
    html_out = main.render_results_page([])
    assert "synced yet" in html_out.lower()


def test_root_shows_top_artists_when_logged_in(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)

    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    user_id = conn.execute("SELECT id FROM users").fetchone()[0]
    db_module.replace_liked_videos(
        conn,
        user_id,
        [
            {"video_id": "v1", "title": "s1", "channel_title": "Radiohead - Topic"},
            {"video_id": "v2", "title": "s2", "channel_title": "Radiohead - Topic"},
            {"video_id": "v3", "title": "s3", "channel_title": "Alt-J"},
        ],
    )
    conn.commit()
    conn.close()

    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "Radiohead" in body
    assert "Radiohead - Topic" not in body  # suffix stripped in display
    assert "Alt-J" in body
    assert body.index("Radiohead") < body.index("Alt-J")  # 2 before 1


def test_root_shows_empty_state_when_logged_in_with_no_liked_videos(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "synced yet" in response.text.lower()
