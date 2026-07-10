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
    db.upsert_track(conn, "v1", "Song One", 180, "2026-07-10T00:00:00")
    run1 = db.start_sync_run(conn, "2026-07-10T00:00:00")
    db.record_history_entry(conn, run1, "v1", 0, "Today")
    run2 = db.start_sync_run(conn, "2026-07-11T00:00:00")
    db.record_history_entry(conn, run2, "v1", 0, "Today")
    rows = conn.execute(
        "SELECT sync_run_id, video_id, position, played_bucket "
        "FROM history_snapshot_entries ORDER BY id"
    ).fetchall()
    assert rows == [(run1, "v1", 0, "Today"), (run2, "v1", 0, "Today")]


def test_link_track_artist_and_finish_sync_run():
    conn = make_conn()
    db.upsert_track(conn, "v1", "Song One", 180, "2026-07-10T00:00:00")
    db.upsert_artist(conn, "artist123", "Some Artist")
    db.link_track_artist(conn, "v1", "artist123", 0)
    link = conn.execute(
        "SELECT video_id, artist_id, position FROM track_artists WHERE video_id = ?", ("v1",)
    ).fetchone()
    assert link == ("v1", "artist123", 0)

    run_id = db.start_sync_run(conn, "2026-07-10T00:00:00")
    db.finish_sync_run(conn, run_id, "2026-07-10T00:05:00", 42)
    run = conn.execute(
        "SELECT started_at, finished_at, items_fetched FROM sync_runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert run == ("2026-07-10T00:00:00", "2026-07-10T00:05:00", 42)
