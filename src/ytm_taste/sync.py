import time
from datetime import datetime, timezone

from ytm_taste import db, lastfm_client, recommendations, youtube_client

RATE_LIMIT_DELAY = 0.25


def run_sync(
    db_path: str,
    user_id: int,
    youtube,
    fetch_liked_videos_fn=youtube_client.fetch_liked_videos,
    fetch_playlists_fn=youtube_client.fetch_playlists,
    fetch_playlist_items_fn=youtube_client.fetch_playlist_items,
    fetch_subscriptions_fn=youtube_client.fetch_subscriptions,
    fetch_video_details_fn=youtube_client.fetch_video_details,
    lastfm_api_key=None,
    fetch_similar_fn=lastfm_client.fetch_similar_tracks,
    sleep_fn=time.sleep,
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

        all_video_ids = [
            item["video_id"] for playlist in playlists for item in playlist["items"]
        ]
        details = fetch_video_details_fn(youtube, all_video_ids)
        for playlist in playlists:
            for item in playlist["items"]:
                d = details.get(item["video_id"], {})
                item["channel_title"] = d.get("channel_title")
                item["category_id"] = d.get("category_id")

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

    recommendation_count = 0
    if lastfm_api_key:
        try:
            clean = db.get_clean_seed_songs(conn, user_id)
            top = db.get_top_artists(conn, user_id)
            seeds = recommendations.select_seeds(clean, top)
            similar_by_seed = []
            for artist, track in seeds:
                similar_by_seed.append(fetch_similar_fn(lastfm_api_key, artist, track))
                sleep_fn(RATE_LIMIT_DELAY)
            owned = db.get_owned_song_keys(conn, user_id)
            recs = recommendations.rank(similar_by_seed, owned)
            db.replace_recommendations(conn, user_id, recs)
            conn.commit()
            recommendation_count = len(recs)
        except Exception as exc:  # best-effort: never affects committed YouTube data
            conn.rollback()
            print(f"Recommendation generation failed (skipped): {exc}")

    elapsed = time.monotonic() - start
    summary = {
        "liked_videos": len(liked_videos),
        "playlists": len(playlists),
        "subscriptions": len(subscriptions),
        "recommendations": recommendation_count,
        "elapsed_seconds": elapsed,
    }
    print(
        f"Synced {summary['liked_videos']} liked videos, {summary['playlists']} playlists, "
        f"{summary['subscriptions']} subscriptions, {summary['recommendations']} recommendations "
        f"in {summary['elapsed_seconds']:.1f}s"
    )
    return summary
