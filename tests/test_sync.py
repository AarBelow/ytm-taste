import pytest

from ytm_taste import db, sync


def fake_liked_videos(youtube):
    return [{"video_id": "v1", "title": "Song One", "channel_title": "Artist One"}]


def fake_playlists(youtube):
    return [{"playlist_id": "PL1", "title": "My Mix"}]


def fake_playlist_items(youtube, playlist_id):
    return [{"video_id": "v2", "title": "Song Two"}]


def fake_subscriptions(youtube):
    return [{"channel_id": "UC1", "channel_title": "Some Artist"}]


def fake_video_details(youtube, video_ids):
    # default: every playlist video resolves to a music track by "PL Artist"
    return {vid: {"channel_title": "PL Artist", "category_id": "10"} for vid in video_ids}


def make_user(db_path, channel_id):
    conn = db.get_connection(db_path)
    db.init_db(conn)
    user_id = db.get_or_create_user(conn, channel_id, "{}", "2026-07-13T00:00:00")
    conn.commit()
    return user_id


def test_run_sync_saves_all_four_data_types(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "UC_user1")
    summary = sync.run_sync(
        db_path,
        user_id,
        youtube=object(),
        fetch_liked_videos_fn=fake_liked_videos,
        fetch_playlists_fn=fake_playlists,
        fetch_playlist_items_fn=fake_playlist_items,
        fetch_subscriptions_fn=fake_subscriptions,
        fetch_video_details_fn=fake_video_details,
    )
    assert summary["liked_videos"] == 1
    assert summary["playlists"] == 1
    assert summary["subscriptions"] == 1

    conn = db.get_connection(db_path)
    liked = conn.execute(
        "SELECT video_id FROM liked_videos WHERE user_id = ?", (user_id,)
    ).fetchall()
    assert liked == [("v1",)]

    playlist_items = conn.execute(
        "SELECT pi.video_id FROM playlist_items pi "
        "JOIN playlists p ON p.id = pi.playlist_row_id WHERE p.user_id = ?",
        (user_id,),
    ).fetchall()
    assert playlist_items == [("v2",)]

    subs = conn.execute(
        "SELECT channel_id FROM subscriptions WHERE user_id = ?", (user_id,)
    ).fetchall()
    assert subs == [("UC1",)]


def test_run_sync_replaces_not_accumulates_on_second_run(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "UC_user1")

    def fetch_liked_v1(youtube):
        return [{"video_id": "v1", "title": "Song One", "channel_title": "Artist One"}]

    def fetch_liked_v2(youtube):
        return [{"video_id": "v2", "title": "Song Two", "channel_title": "Artist Two"}]

    def no_playlists(youtube):
        return []

    def no_subs(youtube):
        return []

    sync.run_sync(
        db_path,
        user_id,
        youtube=object(),
        fetch_liked_videos_fn=fetch_liked_v1,
        fetch_playlists_fn=no_playlists,
        fetch_playlist_items_fn=fake_playlist_items,
        fetch_subscriptions_fn=no_subs,
        fetch_video_details_fn=fake_video_details,
    )
    sync.run_sync(
        db_path,
        user_id,
        youtube=object(),
        fetch_liked_videos_fn=fetch_liked_v2,
        fetch_playlists_fn=no_playlists,
        fetch_playlist_items_fn=fake_playlist_items,
        fetch_subscriptions_fn=no_subs,
        fetch_video_details_fn=fake_video_details,
    )

    conn = db.get_connection(db_path)
    videos = conn.execute(
        "SELECT video_id FROM liked_videos WHERE user_id = ?", (user_id,)
    ).fetchall()
    assert videos == [("v2",)]


def test_run_sync_rolls_back_all_writes_on_failure(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "UC_user1")

    def failing_fetch(youtube):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        sync.run_sync(
            db_path,
            user_id,
            youtube=object(),
            fetch_liked_videos_fn=fake_liked_videos,
            fetch_playlists_fn=failing_fetch,
            fetch_playlist_items_fn=fake_playlist_items,
            fetch_subscriptions_fn=fake_subscriptions,
        )

    conn = db.get_connection(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM liked_videos WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    assert count == 0
    runs = conn.execute(
        "SELECT COUNT(*) FROM sync_runs WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    assert runs == 0


def test_run_sync_keeps_different_users_data_separated(tmp_path):
    db_path = str(tmp_path / "test.db")
    user1 = make_user(db_path, "UC_user1")
    user2 = make_user(db_path, "UC_user2")

    def no_playlists(youtube):
        return []

    def no_subs(youtube):
        return []

    def no_liked(youtube):
        return []

    sync.run_sync(
        db_path,
        user1,
        youtube=object(),
        fetch_liked_videos_fn=fake_liked_videos,
        fetch_playlists_fn=no_playlists,
        fetch_playlist_items_fn=fake_playlist_items,
        fetch_subscriptions_fn=no_subs,
        fetch_video_details_fn=fake_video_details,
    )
    sync.run_sync(
        db_path,
        user2,
        youtube=object(),
        fetch_liked_videos_fn=no_liked,
        fetch_playlists_fn=no_playlists,
        fetch_playlist_items_fn=fake_playlist_items,
        fetch_subscriptions_fn=no_subs,
        fetch_video_details_fn=fake_video_details,
    )

    conn = db.get_connection(db_path)
    user1_videos = conn.execute(
        "SELECT COUNT(*) FROM liked_videos WHERE user_id = ?", (user1,)
    ).fetchone()[0]
    user2_videos = conn.execute(
        "SELECT COUNT(*) FROM liked_videos WHERE user_id = ?", (user2,)
    ).fetchone()[0]
    assert user1_videos == 1
    assert user2_videos == 0


def test_run_sync_enriches_playlist_items_with_channel_and_category(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "UC_user1")

    def one_playlist(youtube):
        return [{"playlist_id": "PL1", "title": "Mix"}]

    def items(youtube, playlist_id):
        return [{"video_id": "v2", "title": "Song Two"}]

    def details(youtube, video_ids):
        return {"v2": {"channel_title": "Real Artist", "category_id": "10"}}

    sync.run_sync(
        db_path,
        user_id,
        youtube=object(),
        fetch_liked_videos_fn=lambda yt: [],
        fetch_playlists_fn=one_playlist,
        fetch_playlist_items_fn=items,
        fetch_subscriptions_fn=lambda yt: [],
        fetch_video_details_fn=details,
    )

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT video_id, channel_title, category_id FROM playlist_items"
    ).fetchone()
    assert row == ("v2", "Real Artist", "10")


def test_run_sync_stores_none_when_video_details_missing(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "UC_user1")

    def one_playlist(youtube):
        return [{"playlist_id": "PL1", "title": "Mix"}]

    def items(youtube, playlist_id):
        return [{"video_id": "v_deleted", "title": "Gone"}]

    def details(youtube, video_ids):
        return {}

    sync.run_sync(
        db_path,
        user_id,
        youtube=object(),
        fetch_liked_videos_fn=lambda yt: [],
        fetch_playlists_fn=one_playlist,
        fetch_playlist_items_fn=items,
        fetch_subscriptions_fn=lambda yt: [],
        fetch_video_details_fn=details,
    )

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT video_id, channel_title, category_id FROM playlist_items"
    ).fetchone()
    assert row == ("v_deleted", None, None)


def test_run_sync_generates_and_stores_recommendations(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "UC_user1")

    def liked(youtube):
        return [{"video_id": "v1", "title": "Seed Song", "channel_title": "Alpha - Topic"}]

    def fetch_similar(api_key, artist, track):
        return [{"artist": "New Artist", "track": "New Song", "match": 0.9}]

    def fetch_meta(artist, track):
        return {"image_url": "http://img/new.jpg", "preview_url": "http://au/new.m4a"}

    summary = sync.run_sync(
        db_path,
        user_id,
        youtube=object(),
        fetch_liked_videos_fn=liked,
        fetch_playlists_fn=lambda yt: [],
        fetch_playlist_items_fn=lambda yt, pid: [],
        fetch_subscriptions_fn=lambda yt: [],
        fetch_video_details_fn=lambda yt, ids: {},
        lastfm_api_key="KEY",
        fetch_similar_fn=fetch_similar,
        fetch_song_meta_fn=fetch_meta,
        fetch_channel_avatars_fn=lambda yt, ids: {},
        fetch_artist_info_fn=lambda k, a: None,
    )
    assert summary["recommendations"] == 1

    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT artist, track, image_url, preview_url FROM recommendations WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    assert row == ("New Artist", "New Song", "http://img/new.jpg", "http://au/new.m4a")


def test_run_sync_stores_recommendation_without_meta_when_itunes_misses(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "UC_user1")

    summary = sync.run_sync(
        db_path,
        user_id,
        youtube=object(),
        fetch_liked_videos_fn=lambda yt: [
            {"video_id": "v1", "title": "Seed", "channel_title": "Alpha - Topic"}
        ],
        fetch_playlists_fn=lambda yt: [],
        fetch_playlist_items_fn=lambda yt, pid: [],
        fetch_subscriptions_fn=lambda yt: [],
        fetch_video_details_fn=lambda yt, ids: {},
        lastfm_api_key="KEY",
        fetch_similar_fn=lambda k, a, t: [{"artist": "N", "track": "S", "match": 0.5}],
        fetch_song_meta_fn=lambda a, t: None,
        fetch_channel_avatars_fn=lambda yt, ids: {},
        fetch_artist_info_fn=lambda k, a: None,
    )
    assert summary["recommendations"] == 1
    conn = db.get_connection(db_path)
    row = conn.execute(
        "SELECT image_url, preview_url FROM recommendations WHERE user_id = ?", (user_id,)
    ).fetchone()
    assert row == (None, None)


def test_run_sync_skips_recommendations_without_api_key(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "UC_user1")

    calls = []
    summary = sync.run_sync(
        db_path,
        user_id,
        youtube=object(),
        fetch_liked_videos_fn=lambda yt: [
            {"video_id": "v1", "title": "S", "channel_title": "Alpha - Topic"}
        ],
        fetch_playlists_fn=lambda yt: [],
        fetch_playlist_items_fn=lambda yt, pid: [],
        fetch_subscriptions_fn=lambda yt: [],
        fetch_video_details_fn=lambda yt, ids: {},
        lastfm_api_key=None,
        fetch_similar_fn=lambda *a: calls.append(a) or [],
    )
    assert summary["recommendations"] == 0
    assert calls == []


def test_run_sync_lastfm_failure_does_not_roll_back_youtube_data(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "UC_user1")

    def boom(api_key, artist, track):
        raise RuntimeError("last.fm down")

    summary = sync.run_sync(
        db_path,
        user_id,
        youtube=object(),
        fetch_liked_videos_fn=lambda yt: [
            {"video_id": "v1", "title": "S", "channel_title": "Alpha - Topic"}
        ],
        fetch_playlists_fn=lambda yt: [],
        fetch_playlist_items_fn=lambda yt, pid: [],
        fetch_subscriptions_fn=lambda yt: [],
        fetch_video_details_fn=lambda yt, ids: {},
        lastfm_api_key="KEY",
        fetch_similar_fn=boom,
        fetch_channel_avatars_fn=lambda yt, ids: {},
        fetch_artist_info_fn=lambda k, a: None,
    )
    assert summary["liked_videos"] == 1
    assert summary["recommendations"] == 0
    conn = db.get_connection(db_path)
    liked = conn.execute(
        "SELECT COUNT(*) FROM liked_videos WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    assert liked == 1
    recs = conn.execute(
        "SELECT COUNT(*) FROM recommendations WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    assert recs == 0


def test_run_sync_populates_artist_details(tmp_path):
    db_path = str(tmp_path / "test.db")
    user_id = make_user(db_path, "UC_user1")

    def liked(youtube):
        return [
            {"video_id": "v1", "title": "s", "channel_title": "Alpha - Topic", "channel_id": "UCa"}
        ]

    def avatars(youtube, channel_ids):
        return {"UCa": "http://av/a.jpg"}

    def artist_info(api_key, artist):
        return {"genre": "indie", "bio": "An artist.", "listeners": 100}

    sync.run_sync(
        db_path,
        user_id,
        youtube=object(),
        fetch_liked_videos_fn=liked,
        fetch_playlists_fn=lambda yt: [],
        fetch_playlist_items_fn=lambda yt, pid: [],
        fetch_subscriptions_fn=lambda yt: [],
        fetch_video_details_fn=lambda yt, ids: {},
        lastfm_api_key="KEY",
        fetch_similar_fn=lambda k, a, t: [],
        fetch_song_meta_fn=lambda a, t: None,
        fetch_channel_avatars_fn=avatars,
        fetch_artist_info_fn=artist_info,
    )
    conn = db.get_connection(db_path)
    details = db.get_artist_details(conn, "Alpha")
    assert details == {
        "avatar_url": "http://av/a.jpg",
        "genre": "indie",
        "bio": "An artist.",
        "listeners": 100,
    }
