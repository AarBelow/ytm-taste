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
            {"video_id": "v1", "title": "s1", "channel_title": "Beta"},
            {"video_id": "v2", "title": "s2", "channel_title": "Alpha"},
            {"video_id": "v3", "title": "s3", "channel_title": "Alpha"},
            {"video_id": "v4", "title": "s4", "channel_title": "Gamma"},
            {"video_id": "v5", "title": "s5", "channel_title": "Gamma"},
        ],
    )
    # Alpha=2, Gamma=2, Beta=1 -> count desc, then title asc for the tie
    assert db.get_top_artists(conn, user_id) == [("Alpha", 2), ("Gamma", 2), ("Beta", 1)]


def test_get_top_artists_only_counts_given_user():
    conn = make_conn()
    user1 = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    user2 = db.get_or_create_user(conn, "UC_user2", "{}", "2026-07-13T00:00:00")
    db.replace_liked_videos(
        conn, user1, [{"video_id": "v1", "title": "s1", "channel_title": "Alpha"}]
    )
    db.replace_liked_videos(
        conn,
        user2,
        [
            {"video_id": "v2", "title": "s2", "channel_title": "Alpha"},
            {"video_id": "v3", "title": "s3", "channel_title": "Alpha"},
        ],
    )
    assert db.get_top_artists(conn, user1) == [("Alpha", 1)]


def test_get_top_artists_empty_for_user_with_no_liked_videos():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "UC_user1", "{}", "2026-07-13T00:00:00")
    assert db.get_top_artists(conn, user_id) == []
