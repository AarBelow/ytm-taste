# tests/test_db.py
import sqlite3

from ytm_taste import db


def make_conn():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    return conn


def test_get_or_create_user_returns_same_id_for_existing_channel_id():
    conn = make_conn()
    first_id = db.get_or_create_user(
        conn, "UC_user1", '{"access_token": "a"}', "2026-07-13T00:00:00"
    )
    second_id = db.get_or_create_user(
        conn, "UC_user1", '{"access_token": "b"}', "2026-07-13T00:01:00"
    )
    assert first_id == second_id
    rows = conn.execute("SELECT id FROM users WHERE channel_id = ?", ("UC_user1",)).fetchall()
    assert len(rows) == 1


def test_get_user_oauth_token_and_update():
    conn = make_conn()
    user_id = db.get_or_create_user(
        conn, "UC_user1", '{"access_token": "a"}', "2026-07-13T00:00:00"
    )
    assert db.get_user_oauth_token(conn, user_id) == '{"access_token": "a"}'
    db.update_user_oauth_token(conn, user_id, '{"access_token": "b"}')
    assert db.get_user_oauth_token(conn, user_id) == '{"access_token": "b"}'


def test_start_and_finish_sync_run():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    run_id = db.start_sync_run(conn, "2026-07-13T00:00:00", user_id)
    db.finish_sync_run(conn, run_id, "2026-07-13T00:05:00", 3)
    run = conn.execute(
        "SELECT started_at, finished_at, items_fetched, user_id FROM sync_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    assert run == ("2026-07-13T00:00:00", "2026-07-13T00:05:00", 3, user_id)


def test_replace_liked_videos_replaces_not_accumulates():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    db.replace_liked_videos(
        conn, user_id, [{"video_id": "v1", "title": "Song One", "channel_title": "A1"}]
    )
    db.replace_liked_videos(
        conn, user_id, [{"video_id": "v2", "title": "Song Two", "channel_title": "A2"}]
    )
    rows = conn.execute(
        "SELECT video_id FROM liked_videos WHERE user_id = ?", (user_id,)
    ).fetchall()
    assert rows == [("v2",)]


def test_replace_liked_videos_keeps_different_users_separated():
    conn = make_conn()
    user1 = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    user2 = db.get_or_create_user(conn, "UC_user2", "{}", "2026-07-13T00:00:00")
    db.replace_liked_videos(
        conn, user1, [{"video_id": "v1", "title": "Song One", "channel_title": "A1"}]
    )
    db.replace_liked_videos(conn, user2, [])
    user1_rows = conn.execute(
        "SELECT video_id FROM liked_videos WHERE user_id = ?", (user1,)
    ).fetchall()
    user2_rows = conn.execute(
        "SELECT video_id FROM liked_videos WHERE user_id = ?", (user2,)
    ).fetchall()
    assert user1_rows == [("v1",)]
    assert user2_rows == []


def test_replace_playlists_stores_items_and_replaces_on_second_call():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    db.replace_playlists(
        conn,
        user_id,
        [
            {
                "playlist_id": "PL1",
                "title": "My Mix",
                "items": [{"video_id": "v1", "title": "Song One"}],
            }
        ],
    )
    rows = conn.execute(
        "SELECT p.playlist_id, pi.video_id FROM playlists p "
        "JOIN playlist_items pi ON pi.playlist_row_id = p.id WHERE p.user_id = ?",
        (user_id,),
    ).fetchall()
    assert rows == [("PL1", "v1")]

    db.replace_playlists(
        conn,
        user_id,
        [
            {
                "playlist_id": "PL2",
                "title": "Another Mix",
                "items": [{"video_id": "v2", "title": "Song Two"}],
            }
        ],
    )
    rows = conn.execute(
        "SELECT p.playlist_id, pi.video_id FROM playlists p "
        "JOIN playlist_items pi ON pi.playlist_row_id = p.id WHERE p.user_id = ?",
        (user_id,),
    ).fetchall()
    assert rows == [("PL2", "v2")]


def test_replace_subscriptions_replaces_not_accumulates():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    db.replace_subscriptions(conn, user_id, [{"channel_id": "UC1", "channel_title": "Artist One"}])
    db.replace_subscriptions(conn, user_id, [{"channel_id": "UC2", "channel_title": "Artist Two"}])
    rows = conn.execute(
        "SELECT channel_id FROM subscriptions WHERE user_id = ?", (user_id,)
    ).fetchall()
    assert rows == [("UC2",)]


def test_get_top_artists_orders_by_count_desc_then_title():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    db.replace_liked_videos(
        conn,
        user_id,
        [
            {"video_id": "v1", "title": "s1", "channel_title": "Beta - Topic"},
            {"video_id": "v2", "title": "s2", "channel_title": "Alpha - Topic"},
            {"video_id": "v3", "title": "s3", "channel_title": "Alpha - Topic"},
            {"video_id": "v4", "title": "s4", "channel_title": "Gamma - Topic"},
            {"video_id": "v5", "title": "s5", "channel_title": "Gamma - Topic"},
        ],
    )
    # Alpha=2, Gamma=2, Beta=1 -> count desc, then title asc for the tie
    assert db.get_top_artists(conn, user_id) == [("Alpha", 2), ("Gamma", 2), ("Beta", 1)]


def test_get_top_artists_only_counts_given_user():
    conn = make_conn()
    user1 = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    user2 = db.get_or_create_user(conn, "UC_user2", "{}", "2026-07-13T00:00:00")
    db.replace_liked_videos(
        conn, user1, [{"video_id": "v1", "title": "s1", "channel_title": "Alpha - Topic"}]
    )
    db.replace_liked_videos(
        conn,
        user2,
        [
            {"video_id": "v2", "title": "s2", "channel_title": "Alpha - Topic"},
            {"video_id": "v3", "title": "s3", "channel_title": "Alpha - Topic"},
        ],
    )
    assert db.get_top_artists(conn, user1) == [("Alpha", 1)]


def test_get_top_artists_empty_for_user_with_no_liked_videos():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    assert db.get_top_artists(conn, user_id) == []


def test_normalize_artist_strips_topic_suffix():
    assert db.normalize_artist("AZALI - Topic") == "AZALI"
    assert db.normalize_artist("AZALI") == "AZALI"
    assert db.normalize_artist("A - Topic B") == "A - Topic B"


def _add_music_playlist(conn, user_id, title, items):
    """items: list of (video_id, item_title, channel_title, category_id)."""
    db.replace_playlists(
        conn,
        user_id,
        [
            {
                "playlist_id": "PL_" + title,
                "title": title,
                "items": [
                    {
                        "video_id": vid,
                        "title": it,
                        "channel_title": ch,
                        "category_id": cat,
                    }
                    for (vid, it, ch, cat) in items
                ],
            }
        ],
    )


def test_replace_playlists_round_trips_channel_and_category():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    _add_music_playlist(
        conn, user_id, "Mix", [("v1", "s1", "Alpha - Topic", "10"), ("v2", "s2", None, None)]
    )
    rows = conn.execute(
        "SELECT video_id, channel_title, category_id FROM playlist_items ORDER BY video_id"
    ).fetchall()
    assert rows == [("v1", "Alpha - Topic", "10"), ("v2", None, None)]


def test_get_top_artists_combines_liked_and_music_playlist_and_normalizes():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    db.replace_liked_videos(
        conn,
        user_id,
        [
            {"video_id": "v1", "title": "s1", "channel_title": "AZALI - Topic"},
            {"video_id": "v2", "title": "s2", "channel_title": "Beta - Topic"},
        ],
    )
    _add_music_playlist(
        conn,
        user_id,
        "Mix",
        [
            ("v3", "s3", "AZALI - Topic", "10"),
            ("v4", "s4", "Beta - Topic", "10"),
            ("v5", "s5", "Some Vlogger", "22"),
        ],
    )
    assert db.get_top_artists(conn, user_id) == [("AZALI", 2), ("Beta", 2)]


def test_get_top_artists_counts_each_occurrence():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    db.replace_liked_videos(
        conn, user_id, [{"video_id": "v1", "title": "s1", "channel_title": "Gamma - Topic"}]
    )
    _add_music_playlist(
        conn,
        user_id,
        "Mix",
        [("v2", "s2", "Gamma - Topic", "10"), ("v3", "s3", "Gamma - Topic", "10")],
    )
    assert db.get_top_artists(conn, user_id) == [("Gamma", 3)]


def test_get_top_artists_playlist_songs_stay_per_user():
    conn = make_conn()
    user1 = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    user2 = db.get_or_create_user(conn, "UC_user2", "{}", "2026-07-13T00:00:00")
    _add_music_playlist(conn, user1, "Mix1", [("v1", "s1", "Alpha - Topic", "10")])
    _add_music_playlist(conn, user2, "Mix2", [("v2", "s2", "Alpha - Topic", "10")])
    assert db.get_top_artists(conn, user1) == [("Alpha", 1)]


def test_get_clean_seed_songs_returns_topic_liked_and_playlist_pairs():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    db.replace_liked_videos(
        conn,
        user_id,
        [
            {"video_id": "v1", "title": "Liked Song", "channel_title": "Alpha - Topic"},
            {"video_id": "v2", "title": "Cover", "channel_title": "Some Uploader"},
        ],
    )
    _add_music_playlist(
        conn,
        user_id,
        "Mix",
        [
            ("v3", "PL Song", "Beta - Topic", "10"),
            ("v4", "Non music", "Gamma - Topic", "22"),
        ],
    )
    seeds = sorted(db.get_clean_seed_songs(conn, user_id))
    assert seeds == [("Alpha", "Liked Song"), ("Beta", "PL Song")]


def test_get_owned_song_keys_lowercases_all_liked_and_music_songs():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    db.replace_liked_videos(
        conn, user_id, [{"video_id": "v1", "title": "HELLO", "channel_title": "Alpha - Topic"}]
    )
    _add_music_playlist(conn, user_id, "Mix", [("v2", "World", "Beta", "10")])
    keys = db.get_owned_song_keys(conn, user_id)
    assert ("alpha", "hello") in keys
    assert ("beta", "world") in keys


def test_replace_and_get_recommendations_round_trip_and_replace():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    db.replace_recommendations(
        conn,
        user_id,
        [
            ("Artist A", "Song A", 2.0, "http://img/a.jpg", "http://au/a.m4a"),
            ("Artist B", "Song B", 1.0, None, None),
        ],
    )
    assert db.get_recommendations(conn, user_id) == [
        ("Artist A", "Song A", 2.0, "http://img/a.jpg", "http://au/a.m4a"),
        ("Artist B", "Song B", 1.0, None, None),
    ]
    db.replace_recommendations(conn, user_id, [("Artist C", "Song C", 5.0, None, None)])
    assert db.get_recommendations(conn, user_id) == [("Artist C", "Song C", 5.0, None, None)]


def test_recommendations_stay_per_user():
    conn = make_conn()
    user1 = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    user2 = db.get_or_create_user(conn, "UC_user2", "{}", "2026-07-13T00:00:00")
    db.replace_recommendations(conn, user1, [("A", "a", 1.0, None, None)])
    db.replace_recommendations(conn, user2, [("B", "b", 2.0, None, None)])
    assert db.get_recommendations(conn, user1) == [("A", "a", 1.0, None, None)]


def test_get_top_artist_channels_maps_normalized_name_to_channel_id():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    db.replace_liked_videos(
        conn,
        user_id,
        [{"video_id": "v1", "title": "s", "channel_title": "AZALI - Topic", "channel_id": "UCaz"}],
    )
    assert db.get_top_artist_channels(conn, user_id) == {"AZALI": "UCaz"}


def test_upsert_and_get_artist_details_round_trip():
    conn = make_conn()
    db.upsert_artist_details(
        conn, "potsu", "http://a/p.jpg", "Lo-Fi", "A producer.", 741785, "http://a/alb.jpg"
    )
    assert db.get_artist_details(conn, "potsu") == {
        "avatar_url": "http://a/p.jpg",
        "genre": "Lo-Fi",
        "bio": "A producer.",
        "listeners": 741785,
        "album_art_url": "http://a/alb.jpg",
    }
    db.upsert_artist_details(conn, "potsu", None, "chill", "Updated.", 1)
    assert db.get_artist_details(conn, "potsu")["bio"] == "Updated."
    assert db.get_artist_details(conn, "potsu")["album_art_url"] is None
    assert db.get_artist_details(conn, "missing") is None


def test_init_db_adds_album_art_url_to_legacy_artist_details():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE artist_details ("
        "artist_name TEXT PRIMARY KEY, avatar_url TEXT, genre TEXT, bio TEXT, listeners INTEGER)"
    )
    conn.execute(
        "INSERT INTO artist_details (artist_name, avatar_url) VALUES ('potsu', 'http://a/p.jpg')"
    )
    conn.commit()
    db.init_db(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(artist_details)").fetchall()]
    assert "album_art_url" in cols
    assert db.get_artist_details(conn, "potsu")["avatar_url"] == "http://a/p.jpg"


def test_sync_ready_toggles_with_syncing_flag():
    conn = make_conn()
    uid = db.get_or_create_user(conn, "UC_s", "{}", "2026-07-15T00:00:00")
    assert db.is_sync_ready(conn, uid) is True  # default 0 -> ready
    db.set_user_syncing(conn, uid, True)
    assert db.is_sync_ready(conn, uid) is False
    db.set_user_syncing(conn, uid, False)
    assert db.is_sync_ready(conn, uid) is True


def test_clear_all_syncing_resets_every_user():
    conn = make_conn()
    a = db.get_or_create_user(conn, "UC_a", "{}", "2026-07-15T00:00:00")
    b = db.get_or_create_user(conn, "UC_b", "{}", "2026-07-15T00:00:00")
    db.set_user_syncing(conn, a, True)
    db.set_user_syncing(conn, b, True)
    assert db.is_sync_ready(conn, a) is False
    db.clear_all_syncing(conn)
    assert db.is_sync_ready(conn, a) is True
    assert db.is_sync_ready(conn, b) is True


def test_init_db_adds_syncing_to_legacy_users():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT UNIQUE "
        "NOT NULL, oauth_token TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO users (channel_id, oauth_token, created_at) VALUES ('UC1','{}','t')"
    )
    conn.commit()
    db.init_db(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    assert "syncing" in cols
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    assert db.is_sync_ready(conn, uid) is True


def test_resolved_songs_round_trip_including_negative_cache():
    conn = make_conn()
    db.upsert_resolved_song(conn, "v1", "android 52", "romance", False, True)
    db.upsert_resolved_song(conn, "v2", None, None, False, False)  # tried and failed
    rows = dict(
        (r[0], (r[1], r[2], r[3], r[4]))
        for r in conn.execute(
            "SELECT video_id, artist, track, is_cover, ok FROM resolved_songs"
        ).fetchall()
    )
    assert rows["v1"] == ("android 52", "romance", 0, 1)
    assert rows["v2"] == (None, None, 0, 0)


def test_get_unresolved_songs_skips_topic_and_already_resolved():
    conn = make_conn()
    uid = db.get_or_create_user(conn, "UC_u", "{}", "2026-07-15T00:00:00")
    db.replace_liked_videos(
        conn,
        uid,
        [
            {"video_id": "v1", "title": "android 52 - romance", "channel_title": "Ethan"},
            {"video_id": "v2", "title": "Song", "channel_title": "Artist - Topic"},
            {"video_id": "v3", "title": "Already Done", "channel_title": "Someone"},
        ],
    )
    db.upsert_resolved_song(conn, "v3", "A", "T", False, True)
    got = db.get_unresolved_songs(conn, uid)
    assert [s["video_id"] for s in got] == ["v1"]
    assert got[0]["channel_title"] == "Ethan"
    assert got[0]["title"] == "android 52 - romance"


def test_get_unresolved_songs_includes_negative_cached_only_once():
    conn = make_conn()
    uid = db.get_or_create_user(conn, "UC_u", "{}", "2026-07-15T00:00:00")
    db.replace_liked_videos(
        conn, uid, [{"video_id": "v1", "title": "junk", "channel_title": "Ch"}]
    )
    db.upsert_resolved_song(conn, "v1", None, None, False, False)
    assert db.get_unresolved_songs(conn, uid) == []  # negative cache prevents retry


def _user_with_songs(conn, songs):
    uid = db.get_or_create_user(conn, "UC_r", "{}", "2026-07-15T00:00:00")
    db.replace_liked_videos(conn, uid, songs)
    return uid


def test_top_artists_credits_resolved_artist_not_the_uploader():
    conn = make_conn()
    uid = _user_with_songs(
        conn, [{"video_id": "v1", "title": "android 52 - romance", "channel_title": "Ethan"}]
    )
    db.upsert_resolved_song(conn, "v1", "android 52", "romance", False, True, 5000)
    assert db.get_top_artists(conn, uid) == [("android 52", 1)]


def test_top_artists_merges_artists_that_differ_only_by_case():
    # YouTube's Topic channel says "Kaz Moon"; Last.fm's canonical spelling is
    # "kaz moon". Same artist -- they must not split into two entries.
    conn = make_conn()
    uid = _user_with_songs(
        conn,
        [
            {"video_id": "v1", "title": "S1", "channel_title": "Kaz Moon - Topic"},
            {"video_id": "v2", "title": "S2", "channel_title": "Kaz Moon - Topic"},
            {"video_id": "v3", "title": "kaz moon - Furious", "channel_title": "Reup"},
        ],
    )
    db.upsert_resolved_song(conn, "v3", "kaz moon", "Furious", False, True, 41363)
    # 2 from the Topic channel + 1 resolved = 3, under the dominant spelling
    assert db.get_top_artists(conn, uid) == [("Kaz Moon", 3)]


def test_top_artists_ignores_low_confidence_resolutions():
    # Listener count is the confidence signal. Junk resolutions ("平行線", "05")
    # sit in the low hundreds; real artists clear the bar. Below it we decline to
    # credit anyone rather than put a fake artist on the page.
    conn = make_conn()
    uid = _user_with_songs(
        conn,
        [
            {"video_id": "v1", "title": "平行線 - Eve x suis", "channel_title": "Eve"},
            {"video_id": "v2", "title": "King Gnu - 白日", "channel_title": "Reup"},
        ],
    )
    db.upsert_resolved_song(conn, "v1", "平行線", "Eve x suis", False, True, 52)
    db.upsert_resolved_song(conn, "v2", "King Gnu", "白日", False, True, 107166)
    assert db.get_top_artists(conn, uid) == [("King Gnu", 1)]


def test_low_confidence_resolutions_still_seed_recommendations():
    # Seeds are permissive: a wrong seed is cheap, and this is where the
    # extra taste coverage comes from.
    conn = make_conn()
    uid = _user_with_songs(
        conn, [{"video_id": "v1", "title": "kaz moon - thought we were a team",
                "channel_title": "Ch"}]
    )
    db.upsert_resolved_song(conn, "v1", "kaz moon", "thought we were a team", False, True, 3)
    assert ("kaz moon", "thought we were a team") in db.get_clean_seed_songs(conn, uid)
    assert db.get_top_artists(conn, uid) == []  # but no credit at 3 listeners


def test_top_artists_excludes_covers_and_unverified():
    conn = make_conn()
    uid = _user_with_songs(
        conn,
        [
            {"video_id": "v1", "title": "Memories - Maroon 5 (cover)", "channel_title": "BC"},
            {"video_id": "v2", "title": "junk", "channel_title": "Reuploader"},
            {"video_id": "v3", "title": "Song", "channel_title": "Real - Topic"},
        ],
    )
    db.upsert_resolved_song(conn, "v1", "Maroon 5", "Memories", True, True)  # cover
    db.upsert_resolved_song(conn, "v2", None, None, False, False)  # unverified
    assert db.get_top_artists(conn, uid) == [("Real", 1)]


def test_clean_seed_songs_includes_resolved_songs_including_covers():
    conn = make_conn()
    uid = _user_with_songs(
        conn,
        [
            {"video_id": "v1", "title": "Memories - Maroon 5 (cover)", "channel_title": "BC"},
            {"video_id": "v2", "title": "Song", "channel_title": "Real - Topic"},
        ],
    )
    db.upsert_resolved_song(conn, "v1", "Maroon 5", "Memories", True, True)
    seeds = db.get_clean_seed_songs(conn, uid)
    assert ("Real", "Song") in seeds
    assert ("Maroon 5", "Memories") in seeds  # covers still seed


def test_owned_song_keys_include_resolved_names():
    conn = make_conn()
    uid = _user_with_songs(
        conn, [{"video_id": "v1", "title": "android 52 - romance", "channel_title": "Ethan"}]
    )
    db.upsert_resolved_song(conn, "v1", "android 52", "romance", False, True)
    assert ("android 52", "romance") in db.get_owned_song_keys(conn, uid)
