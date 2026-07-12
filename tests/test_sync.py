import sqlite3

import pytest

from ytm_taste import db, sync


def fake_songs():
    return [
        {
            "videoId": "v1",
            "title": "Song One",
            "duration_seconds": 200,
            "artists": [{"id": "a1", "name": "Artist One"}],
            "played": "Today",
        },
        {
            "videoId": "v2",
            "title": "Song Two",
            "duration_seconds": 210,
            "artists": [{"id": None, "name": "Artist Two"}],
            "played": "Yesterday",
        },
    ]


def make_user(db_path, channel_handle):
    conn = db.get_connection(db_path)
    db.init_db(conn)
    user_id = db.get_or_create_user(conn, channel_handle, "{}", "2026-07-10T00:00:00")
    conn.commit()
    return user_id


def test_run_sync_saves_fetched_history_to_database(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "@user1")
    summary = sync.run_sync(
        db_path,
        user_id,
        client=object(),
        fetch_history_fn=lambda client: fake_songs(),
    )
    assert summary["items_fetched"] == 2
    assert summary["new_tracks"] == 2

    conn = db.get_connection(db_path)
    tracks = conn.execute("SELECT video_id, title FROM tracks ORDER BY video_id").fetchall()
    assert tracks == [("v1", "Song One"), ("v2", "Song Two")]

    artists = conn.execute("SELECT artist_id, name FROM artists ORDER BY artist_id").fetchall()
    assert artists == [("a1", "Artist One"), ("noid:Artist Two", "Artist Two")]


def test_run_sync_accumulates_across_two_runs(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "@user1")
    sync.run_sync(db_path, user_id, client=object(), fetch_history_fn=lambda client: fake_songs())
    summary2 = sync.run_sync(
        db_path, user_id, client=object(), fetch_history_fn=lambda client: fake_songs()
    )
    assert summary2["items_fetched"] == 2
    assert summary2["new_tracks"] == 0

    conn = db.get_connection(db_path)
    entries = conn.execute("SELECT COUNT(*) FROM history_snapshot_entries").fetchone()[0]
    assert entries == 4

    runs = conn.execute(
        "SELECT COUNT(*) FROM sync_runs WHERE finished_at IS NOT NULL"
    ).fetchone()[0]
    assert runs == 2


def test_run_sync_skips_songs_without_video_id(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "@user1")
    songs = fake_songs() + [
        {"videoId": None, "title": "Bad Song", "artists": [], "played": "Today"}
    ]
    summary = sync.run_sync(
        db_path, user_id, client=object(), fetch_history_fn=lambda client: songs
    )
    assert summary["items_fetched"] == 3
    conn = db.get_connection(db_path)
    count = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    assert count == 2


def test_run_sync_rolls_back_all_writes_on_mid_loop_failure(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "@user1")
    songs_with_bad_second_entry = [
        fake_songs()[0],
        {"videoId": "v_bad", "title": None, "artists": [], "played": "Today"},
    ]

    with pytest.raises(sqlite3.IntegrityError):
        sync.run_sync(
            db_path,
            user_id,
            client=object(),
            fetch_history_fn=lambda client: songs_with_bad_second_entry,
        )

    conn = db.get_connection(db_path)
    tracks = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    assert tracks == 0
    sync_runs = conn.execute(
        "SELECT COUNT(*) FROM sync_runs WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    assert sync_runs == 0


def test_run_sync_keeps_different_users_history_separated(tmp_path):
    db_path = str(tmp_path / "test.db")
    user1 = make_user(db_path, "@user1")
    user2 = make_user(db_path, "@user2")

    sync.run_sync(db_path, user1, client=object(), fetch_history_fn=lambda client: fake_songs())
    sync.run_sync(
        db_path, user2, client=object(), fetch_history_fn=lambda client: [fake_songs()[0]]
    )

    conn = db.get_connection(db_path)
    user1_runs = conn.execute("SELECT id FROM sync_runs WHERE user_id = ?", (user1,)).fetchall()
    user2_runs = conn.execute("SELECT id FROM sync_runs WHERE user_id = ?", (user2,)).fetchall()
    assert len(user1_runs) == 1
    assert len(user2_runs) == 1

    user1_entries = conn.execute(
        "SELECT COUNT(*) FROM history_snapshot_entries WHERE sync_run_id = ?",
        (user1_runs[0][0],),
    ).fetchone()[0]
    user2_entries = conn.execute(
        "SELECT COUNT(*) FROM history_snapshot_entries WHERE sync_run_id = ?",
        (user2_runs[0][0],),
    ).fetchone()[0]
    assert user1_entries == 2
    assert user2_entries == 1

    track_count = conn.execute("SELECT COUNT(*) FROM tracks WHERE video_id = 'v1'").fetchone()[0]
    assert track_count == 1
