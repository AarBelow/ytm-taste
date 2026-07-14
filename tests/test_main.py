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


def _artist(name, avatar=None, genre=None, bio=None, listeners=None):
    return {"name": name, "avatar": avatar, "genre": genre, "bio": bio, "listeners": listeners}


def test_render_results_page_lists_artists_in_order():
    html_out = main.render_results_page([_artist("Alpha"), _artist("Beta")])
    assert "Alpha" in html_out
    assert "Beta" in html_out
    # first artist appears before the second in the document
    assert html_out.index("Alpha") < html_out.index("Beta")


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


def test_root_page_reflects_combined_liked_and_playlist_tally(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)

    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    user_id = conn.execute("SELECT id FROM users").fetchone()[0]
    # "Both": 1 liked + 1 playlist = 2; "PlaylistOnly": 1 playlist = 1
    db_module.replace_liked_videos(
        conn, user_id, [{"video_id": "v1", "title": "s1", "channel_title": "Both"}]
    )
    db_module.replace_playlists(
        conn,
        user_id,
        [
            {
                "playlist_id": "PL1",
                "title": "Mix",
                "items": [
                    {"video_id": "v2", "title": "s2", "channel_title": "Both",
                     "category_id": "10"},
                    {"video_id": "v3", "title": "s3", "channel_title": "PlaylistOnly",
                     "category_id": "10"},
                ],
            }
        ],
    )
    conn.commit()
    conn.close()

    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "Both" in body and "PlaylistOnly" in body
    assert body.index("Both") < body.index("PlaylistOnly")  # 2 ranks above 1


def test_root_shows_empty_state_when_logged_in_with_no_liked_videos(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "synced yet" in response.text.lower()


def test_home_page_links_to_recommendations(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    response = client.get("/")
    assert "/recommendations" in response.text


def test_recommendations_redirects_to_login_when_not_logged_in():
    client = TestClient(main.app, follow_redirects=False)
    response = client.get("/recommendations")
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/login"


def test_recommendations_page_shows_cards_with_cover_and_audio(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)

    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    user_id = conn.execute("SELECT id FROM users").fetchone()[0]
    db_module.replace_recommendations(
        conn,
        user_id,
        [("Boards of Canada", "Roygbiv", 3.0, "http://img/roy.jpg", "http://au/roy.m4a")],
    )
    conn.commit()
    conn.close()

    body = client.get("/recommendations").text
    assert "Boards of Canada" in body
    assert "Roygbiv" in body
    assert "http://img/roy.jpg" in body
    assert "http://au/roy.m4a" in body
    assert "<audio" in body
    assert "#7c3aed" in body.lower() or "--primary" in body


def test_recommendations_page_has_show_more_when_over_five(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)

    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    user_id = conn.execute("SELECT id FROM users").fetchone()[0]
    recs = [(f"A{i}", f"T{i}", float(10 - i), None, None) for i in range(7)]
    db_module.replace_recommendations(conn, user_id, recs)
    conn.commit()
    conn.close()

    body = client.get("/recommendations").text
    assert "more-btn" in body
    assert body.count("card") >= 7
    assert "hidden" in body


def test_home_shows_at_most_five_artists(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    user_id = conn.execute("SELECT id FROM users").fetchone()[0]
    liked = []
    for n, count in [(6, 6), (5, 5), (4, 4), (3, 3), (2, 2), (1, 1)]:
        for i in range(count):
            liked.append({"video_id": f"v{n}_{i}", "title": "s", "channel_title": f"Artist{n}"})
    db_module.replace_liked_videos(conn, user_id, liked)
    conn.commit()
    conn.close()

    body = client.get("/").text
    assert "Artist6" in body and "Artist2" in body
    assert "Artist1" not in body


def test_home_uses_dark_theme(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    body = client.get("/").text
    assert "#7c3aed" in body.lower() or "--primary" in body


def test_home_renders_artist_profile_cards(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    user_id = conn.execute("SELECT id FROM users").fetchone()[0]
    db_module.replace_liked_videos(
        conn, user_id, [{"video_id": "v1", "title": "s", "channel_title": "Alpha"}]
    )
    db_module.upsert_artist_details(
        conn, "Alpha", "http://av/a.jpg", "indie", "An artist bio.", 12345, "http://alb/a.jpg"
    )
    conn.commit()
    conn.close()

    body = client.get("/").text
    assert "Alpha" in body
    assert "indie" in body
    assert "An artist bio." in body
    # avatar is served through our proxy, not hotlinked from Google
    assert "/artist-avatar?artist=Alpha" in body
    assert "listeners" in body.lower()
    assert "http://alb/a.jpg" in body
    assert "background-image" in body


def test_home_links_artist_card_to_youtube_channel(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    user_id = conn.execute("SELECT id FROM users").fetchone()[0]
    db_module.replace_liked_videos(
        conn,
        user_id,
        [{"video_id": "v1", "title": "s", "channel_title": "Alpha", "channel_id": "UC_alpha"}],
    )
    db_module.upsert_artist_details(conn, "Alpha", None, None, None, None)
    conn.commit()
    conn.close()

    body = client.get("/").text
    assert "https://www.youtube.com/channel/UC_alpha" in body


def test_artist_avatar_proxy_serves_fetched_bytes(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    db_module.upsert_artist_details(conn, "Alpha", "http://av/a.jpg", None, None, None)
    conn.commit()
    conn.close()

    class FakeResp:
        headers = {"Content-Type": "image/png"}
        content = b"PNGDATA"

    monkeypatch.setattr(main, "_avatar_cache", {})
    monkeypatch.setattr(main.requests, "get", lambda url, timeout=10: FakeResp())

    r = client.get("/artist-avatar?artist=Alpha")
    assert r.status_code == 200
    assert r.content == b"PNGDATA"
    assert r.headers["content-type"].startswith("image/png")


def test_artist_avatar_proxy_caches_after_first_fetch(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    db_module.upsert_artist_details(conn, "Alpha", "http://av/a.jpg", None, None, None)
    conn.commit()
    conn.close()

    calls = {"n": 0}

    class FakeResp:
        headers = {"Content-Type": "image/jpeg"}
        content = b"JPEGDATA"

    def fake_get(url, timeout=10):
        calls["n"] += 1
        return FakeResp()

    monkeypatch.setattr(main, "_avatar_cache", {})
    monkeypatch.setattr(main.requests, "get", fake_get)

    client.get("/artist-avatar?artist=Alpha")
    client.get("/artist-avatar?artist=Alpha")
    assert calls["n"] == 1  # second request served from cache


def test_artist_avatar_proxy_404_when_no_avatar(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    db_module.upsert_artist_details(conn, "Alpha", None, None, None, None)
    conn.commit()
    conn.close()

    r = client.get("/artist-avatar?artist=Alpha")
    assert r.status_code == 404


def test_home_no_channel_link_when_channel_id_missing(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    user_id = conn.execute("SELECT id FROM users").fetchone()[0]
    db_module.replace_liked_videos(
        conn, user_id, [{"video_id": "v1", "title": "s", "channel_title": "Alpha"}]
    )
    conn.commit()
    conn.close()

    body = client.get("/").text
    assert "Alpha" in body
    assert "youtube.com/channel/" not in body
