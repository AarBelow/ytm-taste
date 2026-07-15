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

    def fake_run_sync(db_path_arg, user_id, youtube, **kwargs):
        # Mirrors real sync.run_sync's finally-block behavior: mark the user
        # ready again once the (fake) sync completes, so tests that log in
        # via this helper land in the "ready" state by default.
        from ytm_taste import db as db_module

        conn = db_module.get_connection(db_path_arg)
        db_module.set_user_syncing(conn, user_id, False)
        conn.commit()
        conn.close()
        return {
            "liked_videos": 0,
            "playlists": 0,
            "subscriptions": 0,
            "elapsed_seconds": 0.0,
        }

    monkeypatch.setattr(main.sync, "run_sync", fake_run_sync)
    client.get("/login")
    client.get("/auth/callback", params={"state": "st", "code": "abc"})
    return db_path


def test_root_logged_out_shows_landing():
    client = TestClient(main.app, follow_redirects=False)
    body = client.get("/").text
    assert "Connect YouTube" in body
    assert "ytm-taste" in body


def test_artists_redirects_to_login_with_next_when_logged_out():
    client = TestClient(main.app, follow_redirects=False)
    r = client.get("/artists")
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/login?next=/artists"


def test_root_logged_in_syncing_shows_loader(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    db_module.set_user_syncing(conn, uid, True)
    conn.commit()
    conn.close()

    body = client.get("/").text
    assert "Tuning in" in body
    assert "/status" in body


def test_root_logged_in_ready_redirects_to_artists(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    # default syncing = 0 -> ready
    r = client.get("/")
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/artists"


def test_status_reports_ready_boolean(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    assert client.get("/status").json() == {"ready": True}
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    db_module.set_user_syncing(conn, uid, True)
    conn.commit()
    conn.close()
    assert client.get("/status").json() == {"ready": False}


def test_safe_next_allowlist():
    assert main._safe_next("/recommendations") == "/recommendations"
    assert main._safe_next("/artists") == "/artists"
    assert main._safe_next("https://evil.example") == "/artists"
    assert main._safe_next(None) == "/artists"


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
            {"video_id": "v3", "title": "s3", "channel_title": "Alt-J - Topic"},
        ],
    )
    conn.commit()
    conn.close()

    response = client.get("/artists")
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
        conn, user_id, [{"video_id": "v1", "title": "s1", "channel_title": "Both - Topic"}]
    )
    db_module.replace_playlists(
        conn,
        user_id,
        [
            {
                "playlist_id": "PL1",
                "title": "Mix",
                "items": [
                    {"video_id": "v2", "title": "s2", "channel_title": "Both - Topic",
                     "category_id": "10"},
                    {"video_id": "v3", "title": "s3", "channel_title": "PlaylistOnly - Topic",
                     "category_id": "10"},
                ],
            }
        ],
    )
    conn.commit()
    conn.close()

    response = client.get("/artists")
    assert response.status_code == 200
    body = response.text
    assert "Both" in body and "PlaylistOnly" in body
    assert body.index("Both") < body.index("PlaylistOnly")  # 2 ranks above 1


def test_root_shows_empty_state_when_logged_in_with_no_liked_videos(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    response = client.get("/artists")
    assert response.status_code == 200
    assert "synced yet" in response.text.lower()


def test_home_page_links_to_recommendations(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    response = client.get("/artists")
    assert "/recommendations" in response.text


def test_recommendations_redirects_to_login_when_not_logged_in():
    client = TestClient(main.app, follow_redirects=False)
    response = client.get("/recommendations")
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/login?next=/recommendations"


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
    assert "refresh-btn" in body
    assert "Refresh" in body
    assert "Show 5 more" not in body  # replaced by the refresh cycle
    assert body.count("card") >= 7
    assert "hidden" in body


def test_recommendations_grid_is_centered():
    # auto-fill left empty tracks that shoved the 5 cards against the left edge.
    recs_rule = main.BASE_STYLES.split(".recs{")[1].split("}")[0]
    assert "justify-content:center" in recs_rule
    assert "auto-fill" not in recs_rule


def test_pagenav_arrow_is_spaced_from_the_title():
    # A trailing space inside CSS `content` does not render; use a margin so the
    # arrow doesn't collide with the page title.
    assert 'content:"\\2190";margin-right' in main.BASE_STYLES
    assert 'content:"\\2192";margin-left' in main.BASE_STYLES


def test_home_shows_at_most_five_artists(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    user_id = conn.execute("SELECT id FROM users").fetchone()[0]
    liked = []
    for n, count in [(6, 6), (5, 5), (4, 4), (3, 3), (2, 2), (1, 1)]:
        for i in range(count):
            liked.append(
                {"video_id": f"v{n}_{i}", "title": "s", "channel_title": f"Artist{n} - Topic"}
            )
    db_module.replace_liked_videos(conn, user_id, liked)
    conn.commit()
    conn.close()

    body = client.get("/artists").text
    assert "Artist6" in body and "Artist2" in body
    assert "Artist1" not in body


def test_home_uses_dark_theme(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    body = client.get("/artists").text
    assert "#7c3aed" in body.lower() or "--primary" in body


def test_home_renders_artist_profile_cards(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    user_id = conn.execute("SELECT id FROM users").fetchone()[0]
    db_module.replace_liked_videos(
        conn, user_id, [{"video_id": "v1", "title": "s", "channel_title": "Alpha - Topic"}]
    )
    db_module.upsert_artist_details(
        conn, "Alpha", "http://av/a.jpg", "indie", "An artist bio.", 12345, "http://alb/a.jpg"
    )
    conn.commit()
    conn.close()

    body = client.get("/artists").text
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
        [
            {
                "video_id": "v1",
                "title": "s",
                "channel_title": "Alpha - Topic",
                "channel_id": "UC_alpha",
            }
        ],
    )
    db_module.upsert_artist_details(conn, "Alpha", None, None, None, None)
    conn.commit()
    conn.close()

    body = client.get("/artists").text
    assert "https://www.youtube.com/channel/UC_alpha" in body


def test_home_renders_hero_and_ranked_list(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    user_id = conn.execute("SELECT id FROM users").fetchone()[0]
    # Alpha appears twice, Beta once -> Alpha is the top (hero), Beta is ranked.
    db_module.replace_liked_videos(
        conn,
        user_id,
        [
            {"video_id": "v1", "title": "s1", "channel_title": "Alpha - Topic"},
            {"video_id": "v2", "title": "s2", "channel_title": "Alpha - Topic"},
            {"video_id": "v3", "title": "s3", "channel_title": "Beta - Topic"},
        ],
    )
    conn.commit()
    conn.close()

    body = client.get("/artists").text
    assert 'class="profile hero"' in body
    assert 'class="ranked"' in body
    assert body.count("Most played") == 1  # only the hero carries the eyebrow
    # hero (Alpha) is rendered above the ranked list (Beta)
    assert body.index("Alpha") < body.index("Beta")


def test_base_styles_includes_painterly_background():
    assert "data:image/svg+xml;base64," in main.BASE_STYLES
    assert "background-attachment:fixed" in main.BASE_STYLES


def test_base_styles_includes_staggered_card_animation():
    assert "@keyframes cardIn" in main.BASE_STYLES
    assert "animation-delay" in main.BASE_STYLES
    # motion-sensitive users get no entrance animation
    assert "prefers-reduced-motion" in main.BASE_STYLES


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
        conn, user_id, [{"video_id": "v1", "title": "s", "channel_title": "Alpha - Topic"}]
    )
    conn.commit()
    conn.close()

    body = client.get("/artists").text
    assert "Alpha" in body
    assert "youtube.com/channel/" not in body


def test_home_shows_landing_for_logged_in_user_with_no_pending_target(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    # First / consumes the pending target from login and forwards to /artists.
    assert client.get("/").headers["location"] == "/artists"
    # Clicking Home afterwards has no pending target, so / is the landing itself.
    body = client.get("/").text
    assert "View your taste" in body
    assert "Connect YouTube" not in body  # already connected


def test_home_still_honours_explicit_next_when_ready(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    client.get("/")  # drain the pending target from login
    r = client.get("/?next=/recommendations")
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/recommendations"


def test_artists_and_recommendations_have_home_button(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    for path in ("/artists", "/recommendations"):
        body = client.get(path).text
        assert 'class="home-link" href="/"' in body


def test_pages_use_docs_style_prev_next_nav(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)

    artists = client.get("/artists").text
    # Next card previews the destination by name, not a bare "click here" link.
    assert 'class="pagenav-link next"' in artists
    assert 'href="/recommendations"' in artists
    assert "Songs You Might Like" in artists
    assert 'aria-label="Next: Songs You Might Like"' in artists
    assert "Songs you might like &rarr;" not in artists  # old bare text link is gone

    recs = client.get("/recommendations").text
    assert 'class="pagenav-link prev"' in recs
    assert 'href="/artists"' in recs
    assert 'aria-label="Previous: Your Top Artists"' in recs
    assert "back to your top artists" not in recs


class FakeStoredCreds:
    def to_json(self):
        return '{"token": "refreshed"}'


def _fake_refresh_deps(monkeypatch):
    """Stand in for the Google token exchange + YouTube client on /refresh."""
    monkeypatch.setattr(google_oauth, "credentials_from_json", lambda raw: FakeStoredCreds())
    monkeypatch.setattr(youtube_client, "build_youtube_client", lambda creds: object())


def test_artists_page_has_a_refresh_button(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    body = client.get("/artists").text
    assert 'action="/refresh?next=/artists"' in body
    assert "Refresh my data" in body


def test_recommendations_page_has_a_refresh_button(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    body = client.get("/recommendations").text
    assert "Refresh my data" in body
    # refreshing from this page must bring you back to this page, not /artists
    assert 'action="/refresh?next=/recommendations"' in body


def test_refresh_returns_to_the_page_it_was_triggered_from(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    _fake_refresh_deps(monkeypatch)
    monkeypatch.setattr(main.sync, "run_sync", lambda *a, **kw: None)

    r = client.post("/refresh?next=/recommendations")
    assert r.headers["location"] == "/?next=/recommendations"


def test_refresh_next_is_allowlisted(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)
    _fake_refresh_deps(monkeypatch)
    monkeypatch.setattr(main.sync, "run_sync", lambda *a, **kw: None)

    r = client.post("/refresh?next=https://evil.example")
    assert r.headers["location"] == "/?next=/artists"  # no open redirect


def test_refresh_requires_login():
    client = TestClient(main.app, follow_redirects=False)
    r = client.post("/refresh")
    assert r.status_code in (302, 303, 307)
    assert r.headers["location"] == "/login?next=/artists"


def test_refresh_starts_a_sync_without_a_new_consent_screen(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    _fake_refresh_deps(monkeypatch)

    calls = []
    monkeypatch.setattr(
        main.sync, "run_sync", lambda db_path_arg, user_id, youtube, **kw: calls.append(user_id)
    )

    r = client.post("/refresh")
    assert r.status_code in (302, 303, 307)
    assert r.headers["location"] == "/?next=/artists"  # lands on the loader
    assert len(calls) == 1  # the sync actually ran

    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    # the refreshed token is persisted back so it stays usable next time
    assert db_module.get_user_oauth_token(conn, uid) == '{"token": "refreshed"}'
    conn.close()


def test_refresh_marks_user_as_syncing_so_the_loader_shows(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    _fake_refresh_deps(monkeypatch)
    # a sync that never finishes, so the syncing flag stays set for us to observe
    monkeypatch.setattr(main.sync, "run_sync", lambda *a, **kw: None)

    client.post("/refresh")
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    assert db_module.is_sync_ready(conn, uid) is False
    conn.close()


def test_refresh_falls_back_to_login_when_the_stored_token_is_dead(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _complete_fake_login(client, monkeypatch, tmp_path)

    def revoked(raw):
        raise ValueError("token has been revoked")

    monkeypatch.setattr(google_oauth, "credentials_from_json", revoked)
    r = client.post("/refresh")
    assert r.status_code in (302, 303, 307)
    assert r.headers["location"] == "/login?next=/artists"


def _with_playlist(db_path, title="Moody", pid="pl1", n=10):
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    db_module.replace_playlists(
        conn,
        uid,
        [
            {
                "playlist_id": pid,
                "title": title,
                "items": [
                    {
                        "video_id": f"{pid}v{i}",
                        "title": f"song {i}",
                        "channel_title": "Beta - Topic",
                        "category_id": "10",
                    }
                    for i in range(n)
                ],
            }
        ],
    )
    conn.commit()
    conn.close()
    return uid


def test_recommendations_page_has_the_fine_tune_wizard(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    uid = _with_playlist(db_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    db_module.replace_recommendations(conn, uid, [("A", "T", 1.0, None, None)])
    conn.commit()
    conn.close()
    body = client.get("/recommendations").text
    assert "Fine-tune" in body
    assert 'id="ft-overlay"' in body
    # all three steps, and the user's seedable playlist offered by name
    assert "Which playlists do you prefer?" in body
    assert "Recommend" in body
    assert "Picks should be" in body
    assert "Moody" in body


def _recs_page_with_prefs(client, monkeypatch, tmp_path, prefs=None):
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    uid = _with_playlist(db_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    db_module.replace_recommendations(conn, uid, [("A", "T", 1.0, None, None)])
    if prefs:
        db_module.set_user_prefs(conn, uid, prefs)
    conn.commit()
    conn.close()
    return db_path, client.get("/recommendations").text


def test_missing_cover_shows_a_styled_placeholder_not_an_empty_box():
    # Apple genuinely lacks some songs (Khantrast, MC Virgins...). An empty box reads
    # as a broken image; show the artist's initial like we already do for avatars.
    page = main.render_recommendations_page([("Khantrast", "I'm Toxic", 1.0, None, None)])
    assert 'class="cover cover-ph"' in page
    assert ">K</div>" in page
    assert ".cover-ph{" in main.BASE_STYLES


def _login_then_wipe_the_user(client, monkeypatch, tmp_path):
    """Log in, then delete the user out from under the live cookie -- exactly what a
    database wipe, restore or bad migration does to every logged-in browser."""
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    return db_path


def test_root_shows_landing_when_the_cookie_names_a_deleted_user(monkeypatch, tmp_path):
    # Without this, "user doesn't exist" reads as "sync not finished" and the visitor
    # is parked on the loader forever, unable to reach the landing page to sign up.
    client = TestClient(main.app, follow_redirects=False)
    _login_then_wipe_the_user(client, monkeypatch, tmp_path)
    body = client.get("/").text
    assert "Connect YouTube" in body
    assert "Tuning in" not in body


def test_a_deleted_user_is_logged_out_not_left_holding_the_cookie(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _login_then_wipe_the_user(client, monkeypatch, tmp_path)
    client.get("/")  # should bin the stale cookie
    assert "Connect YouTube" in client.get("/").text  # and stay logged out


def test_artists_sends_a_deleted_user_to_login(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _login_then_wipe_the_user(client, monkeypatch, tmp_path)
    r = client.get("/artists")
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/login?next=/artists"


def test_status_says_not_ready_for_a_deleted_user_without_looping(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _login_then_wipe_the_user(client, monkeypatch, tmp_path)
    assert client.get("/status").json() == {"ready": False}


def test_hidden_overlay_and_menu_actually_stay_hidden():
    # `display:flex` on these beats the browser's own [hidden]{display:none} at equal
    # specificity, so without an explicit rule the wizard renders OPEN on page load and
    # the close button appears to do nothing. Compound selectors win regardless of order.
    assert ".ft-overlay[hidden]" in main.BASE_STYLES
    assert ".ft-menu[hidden]" in main.BASE_STYLES


def test_fine_tune_is_behind_a_gear_menu_not_a_bare_button(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _db, body = _recs_page_with_prefs(client, monkeypatch, tmp_path)
    assert 'id="ft-gear"' in body
    assert 'id="ft-menu"' in body  # the menu holding Fine-tune, revealed on click


def test_reset_button_hidden_when_nothing_is_tuned(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _db, body = _recs_page_with_prefs(client, monkeypatch, tmp_path)
    assert 'id="ft-reset"' not in body  # nothing to reset


def test_reset_button_shown_once_preferences_are_active(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    _db, body = _recs_page_with_prefs(
        client, monkeypatch, tmp_path,
        prefs={"playlists": ["pl1"], "discovery": "new", "mode": "safe"},
    )
    assert 'id="ft-reset"' in body


def test_posting_defaults_resets_tuning(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path, _body = _recs_page_with_prefs(
        client, monkeypatch, tmp_path,
        prefs={"playlists": ["pl1"], "discovery": "new", "mode": "adventurous"},
    )
    monkeypatch.setattr(main.sync, "rerank", lambda db_p, uid, **kw: None)
    client.post("/fine-tune", json={"playlists": [], "discovery": "mix", "mode": "safe"})
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    assert db_module.get_user_prefs(conn, uid) == db_module.DEFAULT_PREFS
    conn.close()


def test_fine_tune_requires_login():
    client = TestClient(main.app, follow_redirects=False)
    r = client.post("/fine-tune", json={"playlists": [], "discovery": "mix", "mode": "safe"})
    assert r.status_code == 401


def test_fine_tune_stores_prefs_and_queues_a_rerank(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    _with_playlist(db_path)
    calls = []
    monkeypatch.setattr(main.sync, "rerank", lambda db_p, uid, **kw: calls.append(uid))

    r = client.post(
        "/fine-tune", json={"playlists": ["pl1"], "discovery": "new", "mode": "adventurous"}
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert len(calls) == 1  # the re-rank ran

    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    assert db_module.get_user_prefs(conn, uid) == {
        "playlists": ["pl1"],
        "discovery": "new",
        "mode": "adventurous",
    }
    conn.close()


def test_fine_tune_clamps_junk_input(monkeypatch, tmp_path):
    client = TestClient(main.app, follow_redirects=False)
    db_path = _complete_fake_login(client, monkeypatch, tmp_path)
    _with_playlist(db_path)
    monkeypatch.setattr(main.sync, "rerank", lambda db_p, uid, **kw: None)

    client.post(
        "/fine-tune",
        json={"playlists": ["pl1", "not-mine"], "discovery": "hack", "mode": "../../etc"},
    )
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    prefs = db_module.get_user_prefs(conn, uid)
    assert prefs["playlists"] == ["pl1"]  # unknown playlist dropped
    assert prefs["discovery"] == "mix"  # unknown value falls back to the default
    assert prefs["mode"] == "safe"
    conn.close()


def test_loading_page_only_navigates_when_ready():
    page = main.render_loading_page("/artists")
    # The ONLY navigation is the ready path. A fail-safe redirect here would
    # ping-pong against /artists' not-ready gate and loop forever.
    assert page.count("window.location.replace") == 1
    assert "slow-note" in page


def test_clear_stale_syncing_clears_flag_left_by_a_dead_process(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(main, "DB_PATH", db_path)
    from ytm_taste import db as db_module

    conn = db_module.get_connection(db_path)
    db_module.init_db(conn)
    uid = db_module.get_or_create_user(conn, "UC_stale", "{}", "2026-07-15T00:00:00")
    db_module.set_user_syncing(conn, uid, True)
    conn.commit()
    conn.close()

    # A freshly started process has no sync in flight, so any flag it finds is stale.
    main._clear_stale_syncing()

    conn = db_module.get_connection(db_path)
    assert db_module.is_sync_ready(conn, uid) is True
    conn.close()


def test_base_styles_includes_landing_and_equalizer():
    assert "@keyframes eqBounce" in main.BASE_STYLES
    assert ".wordmark" in main.BASE_STYLES
    assert ".tile" in main.BASE_STYLES
