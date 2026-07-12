import time
from datetime import datetime, timezone

from ytm_taste import db, ytmusic_client


def run_sync(
    db_path: str,
    user_id: int,
    client,
    fetch_history_fn=ytmusic_client.fetch_history,
) -> dict:
    start = time.monotonic()
    conn = db.get_connection(db_path)
    db.init_db(conn)

    try:
        now = datetime.now(timezone.utc).isoformat()
        sync_run_id = db.start_sync_run(conn, now, user_id)

        songs = fetch_history_fn(client)

        new_track_ids = set()
        for position, song in enumerate(songs):
            video_id = song.get("videoId")
            if not video_id:
                continue

            existing = conn.execute(
                "SELECT 1 FROM tracks WHERE video_id = ?", (video_id,)
            ).fetchone()
            if existing is None:
                new_track_ids.add(video_id)

            db.upsert_track(conn, video_id, song.get("title"), song.get("duration_seconds"), now)

            for artist_position, artist in enumerate(song.get("artists") or []):
                artist_id = artist.get("id") or f"noid:{artist.get('name')}"
                db.upsert_artist(conn, artist_id, artist.get("name"))
                db.link_track_artist(conn, video_id, artist_id, artist_position)

            db.record_history_entry(conn, sync_run_id, video_id, position, song.get("played"))

        db.finish_sync_run(conn, sync_run_id, datetime.now(timezone.utc).isoformat(), len(songs))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    elapsed = time.monotonic() - start
    summary = {
        "items_fetched": len(songs),
        "new_tracks": len(new_track_ids),
        "elapsed_seconds": elapsed,
    }
    print(
        f"Synced {summary['items_fetched']} history entries "
        f"({summary['new_tracks']} new tracks) in {summary['elapsed_seconds']:.1f}s"
    )
    return summary
