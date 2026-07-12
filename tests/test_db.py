# tests/test_db.py
import sqlite3

from ytm_taste import db


def make_conn():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    return conn


def test_upsert_track_inserts_new_track():
    conn = make_conn()
    db.upsert_track(conn, "v1", "Song One", 180, "2026-07-10T00:00:00")
    row = conn.execute(
        "SELECT video_id, title, duration_seconds, first_seen_at, last_seen_at "
        "FROM tracks WHERE video_id = ?",
        ("v1",),
    ).fetchone()
    assert row == ("v1", "Song One", 180, "2026-07-10T00:00:00", "2026-07-10T00:00:00")


def test_upsert_track_updates_last_seen_at_without_duplicating():
    conn = make_conn()
    db.upsert_track(conn, "v1", "Song One", 180, "2026-07-10T00:00:00")
    db.upsert_track(conn, "v1", "Song One", 180, "2026-07-11T00:00:00")
    rows = conn.execute(
        "SELECT first_seen_at, last_seen_at FROM tracks WHERE video_id = ?", ("v1",)
    ).fetchall()
    assert rows == [("2026-07-10T00:00:00", "2026-07-11T00:00:00")]


def test_upsert_artist_with_no_id_uses_name_fallback_without_colliding():
    conn = make_conn()
    db.upsert_artist(conn, "artist123", "Same Name")
    db.upsert_artist(conn, "noid:Same Name", "Same Name")
    rows = conn.execute("SELECT artist_id, name FROM artists ORDER BY artist_id").fetchall()
    assert rows == [("artist123", "Same Name"), ("noid:Same Name", "Same Name")]


def test_two_sync_runs_record_separate_history_entries_for_same_track():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "@user1", "{}", "2026-07-10T00:00:00")
    db.upsert_track(conn, "v1", "Song One", 180, "2026-07-10T00:00:00")
    run1 = db.start_sync_run(conn, "2026-07-10T00:00:00", user_id)
    db.record_history_entry(conn, run1, "v1", 0, "Today")
    run2 = db.start_sync_run(conn, "2026-07-11T00:00:00", user_id)
    db.record_history_entry(conn, run2, "v1", 0, "Today")
    rows = conn.execute(
        "SELECT sync_run_id, video_id, position, played_bucket "
        "FROM history_snapshot_entries ORDER BY id"
    ).fetchall()
    assert rows == [(run1, "v1", 0, "Today"), (run2, "v1", 0, "Today")]


def test_link_track_artist_and_finish_sync_run():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "@user1", "{}", "2026-07-10T00:00:00")
    db.upsert_track(conn, "v1", "Song One", 180, "2026-07-10T00:00:00")
    db.upsert_artist(conn, "artist123", "Some Artist")
    db.link_track_artist(conn, "v1", "artist123", 0)
    link = conn.execute(
        "SELECT video_id, artist_id, position FROM track_artists WHERE video_id = ?", ("v1",)
    ).fetchone()
    assert link == ("v1", "artist123", 0)

    run_id = db.start_sync_run(conn, "2026-07-10T00:00:00", user_id)
    db.finish_sync_run(conn, run_id, "2026-07-10T00:05:00", 42)
    run = conn.execute(
        "SELECT started_at, finished_at, items_fetched, user_id FROM sync_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    assert run == ("2026-07-10T00:00:00", "2026-07-10T00:05:00", 42, user_id)


def test_get_or_create_user_returns_same_id_for_existing_channel_handle():
    conn = make_conn()
    first_id = db.get_or_create_user(
        conn, "@user1", '{"access_token": "a"}', "2026-07-10T00:00:00"
    )
    second_id = db.get_or_create_user(
        conn, "@user1", '{"access_token": "b"}', "2026-07-10T00:01:00"
    )
    assert first_id == second_id
    rows = conn.execute("SELECT id FROM users WHERE channel_handle = ?", ("@user1",)).fetchall()
    assert len(rows) == 1


def test_two_users_sync_runs_stay_separated():
    conn = make_conn()
    user1 = db.get_or_create_user(conn, "@user1", "{}", "2026-07-10T00:00:00")
    user2 = db.get_or_create_user(conn, "@user2", "{}", "2026-07-10T00:00:00")

    db.upsert_track(conn, "v1", "Song One", 180, "2026-07-10T00:00:00")

    run1 = db.start_sync_run(conn, "2026-07-10T00:00:00", user1)
    db.record_history_entry(conn, run1, "v1", 0, "Today")

    run2 = db.start_sync_run(conn, "2026-07-10T00:00:00", user2)
    db.record_history_entry(conn, run2, "v1", 0, "Today")

    user1_runs = conn.execute("SELECT id FROM sync_runs WHERE user_id = ?", (user1,)).fetchall()
    user2_runs = conn.execute("SELECT id FROM sync_runs WHERE user_id = ?", (user2,)).fetchall()
    assert user1_runs == [(run1,)]
    assert user2_runs == [(run2,)]


def test_get_user_oauth_token_and_update():
    conn = make_conn()
    user_id = db.get_or_create_user(conn, "@user1", '{"access_token": "a"}', "2026-07-10T00:00:00")
    assert db.get_user_oauth_token(conn, user_id) == '{"access_token": "a"}'
    db.update_user_oauth_token(conn, user_id, '{"access_token": "b"}')
    assert db.get_user_oauth_token(conn, user_id) == '{"access_token": "b"}'
