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


def test_run_sync_saves_fetched_history_to_database(tmp_path):
    db_path = str(tmp_path / "test.db")
    summary = sync.run_sync(
        db_path,
        "unused.json",
        fetch_history_fn=lambda client: fake_songs(),
        client=object(),
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
    sync.run_sync(
        db_path, "unused.json", fetch_history_fn=lambda client: fake_songs(), client=object()
    )
    summary2 = sync.run_sync(
        db_path, "unused.json", fetch_history_fn=lambda client: fake_songs(), client=object()
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
    songs = fake_songs() + [
        {"videoId": None, "title": "Bad Song", "artists": [], "played": "Today"}
    ]
    summary = sync.run_sync(
        db_path, "unused.json", fetch_history_fn=lambda client: songs, client=object()
    )
    assert summary["items_fetched"] == 3
    conn = db.get_connection(db_path)
    count = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    assert count == 2


def test_run_sync_raises_clear_error_when_auth_file_missing(tmp_path):
    db_path = str(tmp_path / "test.db")
    missing_auth = str(tmp_path / "missing.json")
    with pytest.raises(RuntimeError, match="ytmusicapi browser"):
        sync.run_sync(db_path, missing_auth)


def test_run_sync_rolls_back_all_writes_on_mid_loop_failure(tmp_path):
    db_path = str(tmp_path / "test.db")
    songs_with_bad_second_entry = [
        fake_songs()[0],
        {"videoId": "v_bad", "title": None, "artists": [], "played": "Today"},
    ]

    with pytest.raises(sqlite3.IntegrityError):
        sync.run_sync(
            db_path,
            "unused.json",
            fetch_history_fn=lambda client: songs_with_bad_second_entry,
            client=object(),
        )

    conn = db.get_connection(db_path)
    tracks = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    assert tracks == 0
    sync_runs = conn.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0]
    assert sync_runs == 0
