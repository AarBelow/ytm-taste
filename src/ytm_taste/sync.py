import time
from datetime import datetime, timezone

from ytm_taste import (
    concurrency,
    db,
    itunes_client,
    lastfm_client,
    recommendations,
    youtube_client,
)


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
    fetch_song_meta_fn=itunes_client.fetch_song_meta,
    fetch_channel_avatars_fn=youtube_client.fetch_channel_avatars,
    fetch_artist_info_fn=lastfm_client.fetch_artist_info,
) -> dict:
    start = time.monotonic()
    conn = db.get_connection(db_path)
    db.init_db(conn)

    try:
        now = datetime.now(timezone.utc).isoformat()
        sync_run_id = db.start_sync_run(conn, now, user_id)

        liked_videos = fetch_liked_videos_fn(youtube)
        playlists = fetch_playlists_fn(youtube)
        # Sequential: shares the non-thread-safe googleapiclient `youtube` object.
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
                item["channel_id"] = d.get("channel_id")

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
            similar_by_seed = concurrency.run_concurrently(
                lambda s: fetch_similar_fn(lastfm_api_key, s[0], s[1]), seeds
            )
            owned = db.get_owned_song_keys(conn, user_id)
            recs = recommendations.rank(similar_by_seed, owned)
            metas = concurrency.run_concurrently(lambda r: fetch_song_meta_fn(r[0], r[1]), recs)
            enriched = [
                (
                    artist,
                    track,
                    score,
                    meta["image_url"] if meta else None,
                    meta["preview_url"] if meta else None,
                )
                for (artist, track, score), meta in zip(recs, metas)
            ]
            db.replace_recommendations(conn, user_id, enriched)
            conn.commit()
            recommendation_count = len(enriched)
        except Exception as exc:  # best-effort: never affects committed YouTube data
            conn.rollback()
            print(f"Recommendation generation failed (skipped): {exc}")

    try:
        top_artists = db.get_top_artists(conn, user_id)[:5]
        channels = db.get_top_artist_channels(conn, user_id)
        wanted = [channels[name] for name, _c in top_artists if name in channels]
        avatars = fetch_channel_avatars_fn(youtube, wanted) if wanted else {}
        if lastfm_api_key:
            infos = concurrency.run_concurrently(
                lambda a: fetch_artist_info_fn(lastfm_api_key, a[0]), top_artists
            )
        else:
            infos = [None] * len(top_artists)
        for (name, _count), info in zip(top_artists, infos):
            channel_id = channels.get(name)
            avatar = avatars.get(channel_id) if channel_id else None
            info = info or {}
            db.upsert_artist_details(
                conn, name, avatar, info.get("genre"), info.get("bio"), info.get("listeners")
            )
        conn.commit()
    except Exception as exc:  # best-effort; never fails the sync
        conn.rollback()
        print(f"Artist-details enrichment failed (skipped): {exc}")

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
