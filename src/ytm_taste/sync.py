import time
from datetime import datetime, timezone

from ytm_taste import db, youtube_client


def run_sync(
    db_path: str,
    user_id: int,
    youtube,
    fetch_liked_videos_fn=youtube_client.fetch_liked_videos,
    fetch_playlists_fn=youtube_client.fetch_playlists,
    fetch_playlist_items_fn=youtube_client.fetch_playlist_items,
    fetch_subscriptions_fn=youtube_client.fetch_subscriptions,
) -> dict:
    start = time.monotonic()
    conn = db.get_connection(db_path)
    db.init_db(conn)

    try:
        now = datetime.now(timezone.utc).isoformat()
        sync_run_id = db.start_sync_run(conn, now, user_id)

        liked_videos = fetch_liked_videos_fn(youtube)
        playlists = fetch_playlists_fn(youtube)
        for playlist in playlists:
            playlist["items"] = fetch_playlist_items_fn(youtube, playlist["playlist_id"])
        subscriptions = fetch_subscriptions_fn(youtube)

        db.replace_liked_videos(conn, user_id, liked_videos)
        db.replace_playlists(conn, user_id, playlists)
        db.replace_subscriptions(conn, user_id, subscriptions)

        total_items = len(liked_videos) + len(playlists) + len(subscriptions)
        db.finish_sync_run(conn, sync_run_id, datetime.now(timezone.utc).isoformat(), total_items)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    elapsed = time.monotonic() - start
    summary = {
        "liked_videos": len(liked_videos),
        "playlists": len(playlists),
        "subscriptions": len(subscriptions),
        "elapsed_seconds": elapsed,
    }
    print(
        f"Synced {summary['liked_videos']} liked videos, {summary['playlists']} playlists, "
        f"{summary['subscriptions']} subscriptions in {summary['elapsed_seconds']:.1f}s"
    )
    return summary
