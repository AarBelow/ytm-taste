import time
from datetime import datetime, timezone

from ytm_taste import (
    concurrency,
    db,
    itunes_client,
    lastfm_client,
    recommendations,
    song_resolver,
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
    fetch_artist_album_art_fn=itunes_client.fetch_artist_album_art,
    verify_track_fn=lastfm_client.verify_track,
) -> dict:
    start = time.monotonic()
    conn = db.get_connection(db_path)
    db.init_db(conn)

    try:
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
            db.finish_sync_run(
                conn, sync_run_id, datetime.now(timezone.utc).isoformat(), total_items
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        if lastfm_api_key:
            try:
                unresolved = db.get_unresolved_songs(conn, user_id)
                results = concurrency.run_concurrently(
                    lambda s: (
                        s,
                        song_resolver.resolve(
                            s["channel_title"],
                            s["title"],
                            lambda a, t: verify_track_fn(lastfm_api_key, a, t),
                        ),
                    ),
                    unresolved,
                )
                for song, found in results:
                    if found:
                        db.upsert_resolved_song(
                            conn, song["video_id"], found["artist"], found["track"],
                            found["is_cover"], True, found.get("listeners", 0),
                        )
                    else:
                        db.upsert_resolved_song(conn, song["video_id"], None, None, False, False)
                conn.commit()
            except Exception as exc:  # best-effort: never affects committed YouTube data
                conn.rollback()
                print(f"Song resolution failed (skipped): {exc}")

        recommendation_count = 0
        if lastfm_api_key:
            try:
                clean = db.get_clean_seed_songs(conn, user_id)
                top = db.get_top_artists(conn, user_id)
                seeds = recommendations.select_seeds(clean, top)
                # Network-bound, so the extra parallelism is free: measured 100 seeds
                # at 10 workers = 3.1s, vs 50 seeds at 5 workers = 4.2s. Kept at 10
                # to stay near Last.fm's ~5 req/s guidance rather than risk throttling.
                similar_by_seed = concurrency.run_concurrently(
                    lambda s: fetch_similar_fn(lastfm_api_key, s[0], s[1]), seeds,
                    max_workers=10,
                )
                owned = db.get_owned_song_keys(conn, user_id)
                recs = recommendations.rank(similar_by_seed, owned)
                metas = concurrency.run_concurrently(
                    lambda r: fetch_song_meta_fn(r[0], r[1]), recs
                )
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
            album_arts = concurrency.run_concurrently(
                lambda a: fetch_artist_album_art_fn(a[0]), top_artists
            )
            for (name, _count), info, album_art in zip(top_artists, infos, album_arts):
                channel_id = channels.get(name)
                avatar = avatars.get(channel_id) if channel_id else None
                info = info or {}
                db.upsert_artist_details(
                    conn, name, avatar, info.get("genre"), info.get("bio"),
                    info.get("listeners"), album_art,
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
            f"{summary['subscriptions']} subscriptions, "
            f"{summary['recommendations']} recommendations "
            f"in {summary['elapsed_seconds']:.1f}s"
        )
        return summary
    finally:
        db.set_user_syncing(conn, user_id, False)
        conn.commit()
        conn.close()


def rerank(
    db_path: str,
    user_id: int,
    lastfm_api_key=None,
    fetch_similar_fn=lastfm_client.fetch_similar_tracks,
    fetch_song_meta_fn=itunes_client.fetch_song_meta,
) -> dict:
    """Rebuild recommendations from the user's fine-tune preferences.

    Deliberately never touches YouTube: preferences change how we select and weigh,
    not what is in the library, so re-reading it would be slow and pointless. Seeds ->
    Last.fm similar -> rank -> covers. Seconds, not the full sync's ~25s.
    """
    start = time.monotonic()
    conn = db.get_connection(db_path)
    db.init_db(conn)
    try:
        count = 0
        if lastfm_api_key:
            try:
                prefs = db.get_user_prefs(conn, user_id)
                pool = db.get_clean_seed_songs(conn, user_id, prefs.get("playlists") or None)
                top = db.get_top_artists(conn, user_id)
                seeds = recommendations.select_seeds(pool, top)
                similar_by_seed = concurrency.run_concurrently(
                    lambda s: fetch_similar_fn(lastfm_api_key, s[0], s[1]), seeds,
                    max_workers=10,
                )
                recs = recommendations.rank(
                    similar_by_seed,
                    db.get_owned_song_keys(conn, user_id),
                    known_artists={name.casefold() for name, _c in top},
                    discovery=prefs.get("discovery"),
                    mode=prefs.get("mode"),
                )
                metas = concurrency.run_concurrently(
                    lambda r: fetch_song_meta_fn(r[0], r[1]), recs
                )
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
                count = len(enriched)
            except Exception as exc:  # best-effort: keep whatever recommendations exist
                conn.rollback()
                print(f"Re-rank failed (skipped): {exc}")
        elapsed = time.monotonic() - start
        print(f"Re-ranked {count} recommendations in {elapsed:.1f}s")
        return {"recommendations": count, "elapsed_seconds": elapsed}
    finally:
        db.set_user_syncing(conn, user_id, False)
        conn.commit()
        conn.close()
