# src/ytm_taste/db.py
import sqlite3
from collections import Counter


def get_connection(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT UNIQUE NOT NULL,
            oauth_token TEXT NOT NULL,
            created_at TEXT NOT NULL,
            syncing INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            items_fetched INTEGER,
            user_id INTEGER NOT NULL REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS liked_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            video_id TEXT NOT NULL,
            title TEXT NOT NULL,
            channel_title TEXT NOT NULL,
            channel_id TEXT
        );

        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            playlist_id TEXT NOT NULL,
            title TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS playlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_row_id INTEGER NOT NULL REFERENCES playlists(id),
            video_id TEXT NOT NULL,
            title TEXT NOT NULL,
            channel_title TEXT,
            category_id TEXT,
            channel_id TEXT
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            channel_id TEXT NOT NULL,
            channel_title TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            artist TEXT NOT NULL,
            track TEXT NOT NULL,
            score REAL NOT NULL,
            image_url TEXT,
            preview_url TEXT
        );

        CREATE TABLE IF NOT EXISTS artist_details (
            artist_name TEXT PRIMARY KEY,
            avatar_url TEXT,
            genre TEXT,
            bio TEXT,
            listeners INTEGER,
            album_art_url TEXT
        );

        CREATE TABLE IF NOT EXISTS resolved_songs (
            video_id TEXT PRIMARY KEY,
            artist TEXT,
            track TEXT,
            is_cover INTEGER NOT NULL DEFAULT 0,
            ok INTEGER NOT NULL
        );
        """
    )
    cols = [r[1] for r in conn.execute("PRAGMA table_info(artist_details)").fetchall()]
    if "album_art_url" not in cols:
        conn.execute("ALTER TABLE artist_details ADD COLUMN album_art_url TEXT")
    ucols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "syncing" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN syncing INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def get_or_create_user(
    conn: sqlite3.Connection, channel_id: str, oauth_token_json: str, now: str
) -> int:
    existing = conn.execute(
        "SELECT id FROM users WHERE channel_id = ?", (channel_id,)
    ).fetchone()
    if existing is not None:
        return existing[0]
    cur = conn.execute(
        "INSERT INTO users (channel_id, oauth_token, created_at) VALUES (?, ?, ?)",
        (channel_id, oauth_token_json, now),
    )
    return cur.lastrowid


def get_user_oauth_token(conn: sqlite3.Connection, user_id: int) -> str:
    row = conn.execute("SELECT oauth_token FROM users WHERE id = ?", (user_id,)).fetchone()
    return row[0]


def update_user_oauth_token(conn: sqlite3.Connection, user_id: int, oauth_token_json: str) -> None:
    conn.execute("UPDATE users SET oauth_token = ? WHERE id = ?", (oauth_token_json, user_id))


def start_sync_run(conn: sqlite3.Connection, started_at: str, user_id: int) -> int:
    cur = conn.execute(
        "INSERT INTO sync_runs (started_at, user_id) VALUES (?, ?)", (started_at, user_id)
    )
    return cur.lastrowid


def finish_sync_run(
    conn: sqlite3.Connection, sync_run_id: int, finished_at: str, items_fetched: int
) -> None:
    conn.execute(
        "UPDATE sync_runs SET finished_at = ?, items_fetched = ? WHERE id = ?",
        (finished_at, items_fetched, sync_run_id),
    )


def replace_liked_videos(conn: sqlite3.Connection, user_id: int, videos: list[dict]) -> None:
    conn.execute("DELETE FROM liked_videos WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO liked_videos (user_id, video_id, title, channel_title, channel_id) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (user_id, v["video_id"], v["title"], v["channel_title"], v.get("channel_id"))
            for v in videos
        ],
    )


def replace_playlists(conn: sqlite3.Connection, user_id: int, playlists: list[dict]) -> None:
    existing_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM playlists WHERE user_id = ?", (user_id,)
        ).fetchall()
    ]
    if existing_ids:
        conn.executemany(
            "DELETE FROM playlist_items WHERE playlist_row_id = ?",
            [(pid,) for pid in existing_ids],
        )
    conn.execute("DELETE FROM playlists WHERE user_id = ?", (user_id,))

    for playlist in playlists:
        cur = conn.execute(
            "INSERT INTO playlists (user_id, playlist_id, title) VALUES (?, ?, ?)",
            (user_id, playlist["playlist_id"], playlist["title"]),
        )
        playlist_row_id = cur.lastrowid
        items = playlist.get("items", [])
        conn.executemany(
            "INSERT INTO playlist_items "
            "(playlist_row_id, video_id, title, channel_title, category_id, channel_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    playlist_row_id,
                    item["video_id"],
                    item["title"],
                    item.get("channel_title"),
                    item.get("category_id"),
                    item.get("channel_id"),
                )
                for item in items
            ],
        )


def replace_subscriptions(
    conn: sqlite3.Connection, user_id: int, subscriptions: list[dict]
) -> None:
    conn.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO subscriptions (user_id, channel_id, channel_title) VALUES (?, ?, ?)",
        [(user_id, s["channel_id"], s["channel_title"]) for s in subscriptions],
    )


def normalize_artist(name: str) -> str:
    suffix = " - Topic"
    if name.endswith(suffix):
        return name[: -len(suffix)]
    return name


def _resolved_for_user(conn, user_id) -> list[tuple[str, str, str, int]]:
    """(video_id, artist, track, is_cover) for this user's successfully resolved songs."""
    return conn.execute(
        """
        SELECT rs.video_id, rs.artist, rs.track, rs.is_cover FROM resolved_songs rs
        WHERE rs.ok = 1 AND rs.video_id IN (
            SELECT video_id FROM liked_videos WHERE user_id = ?
            UNION
            SELECT pi.video_id FROM playlist_items pi
            JOIN playlists p ON p.id = pi.playlist_row_id
            WHERE p.user_id = ? AND pi.category_id = '10'
        )
        """,
        (user_id, user_id),
    ).fetchall()


def get_top_artists(conn: sqlite3.Connection, user_id: int) -> list[tuple[str, int]]:
    rows = conn.execute(
        """
        SELECT video_id, channel_title FROM liked_videos WHERE user_id = ?
        UNION ALL
        SELECT pi.video_id, pi.channel_title
        FROM playlist_items pi
        JOIN playlists p ON p.id = pi.playlist_row_id
        WHERE p.user_id = ? AND pi.category_id = '10'
        """,
        (user_id, user_id),
    ).fetchall()
    resolved = {
        vid: (artist, is_cover)
        for vid, artist, _track, is_cover in _resolved_for_user(conn, user_id)
    }
    counts: Counter = Counter()
    for video_id, channel_title in rows:
        if channel_title and channel_title.endswith(" - Topic"):
            counts[normalize_artist(channel_title)] += 1
            continue
        entry = resolved.get(video_id)
        if entry is None:
            continue  # unverified: no credit
        artist, is_cover = entry
        if is_cover or not artist:
            continue  # covers seed but never get credit
        counts[artist] += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def get_clean_seed_songs(conn: sqlite3.Connection, user_id: int) -> list[tuple[str, str]]:
    rows = conn.execute(
        """
        SELECT channel_title, title FROM liked_videos
        WHERE user_id = ? AND channel_title LIKE '% - Topic'
        UNION ALL
        SELECT pi.channel_title, pi.title
        FROM playlist_items pi
        JOIN playlists p ON p.id = pi.playlist_row_id
        WHERE p.user_id = ? AND pi.category_id = '10'
              AND pi.channel_title LIKE '% - Topic'
        """,
        (user_id, user_id),
    ).fetchall()
    seeds = [(normalize_artist(channel), title) for channel, title in rows]
    for _vid, artist, track, _is_cover in _resolved_for_user(conn, user_id):
        if artist and track:
            seeds.append((artist, track))
    return seeds


def get_owned_song_keys(conn: sqlite3.Connection, user_id: int) -> set[tuple[str, str]]:
    rows = conn.execute(
        """
        SELECT channel_title, title FROM liked_videos WHERE user_id = ?
        UNION ALL
        SELECT pi.channel_title, pi.title
        FROM playlist_items pi
        JOIN playlists p ON p.id = pi.playlist_row_id
        WHERE p.user_id = ? AND pi.category_id = '10'
        """,
        (user_id, user_id),
    ).fetchall()
    keys = set()
    for channel, title in rows:
        if channel is None:
            continue
        keys.add((normalize_artist(channel).lower().strip(), title.lower().strip()))
    for _vid, artist, track, _is_cover in _resolved_for_user(conn, user_id):
        if artist and track:
            keys.add((artist.lower().strip(), track.lower().strip()))
    return keys


def replace_recommendations(conn: sqlite3.Connection, user_id: int, recs) -> None:
    conn.execute("DELETE FROM recommendations WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO recommendations (user_id, artist, track, score, image_url, preview_url) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (user_id, artist, track, score, image_url, preview_url)
            for (artist, track, score, image_url, preview_url) in recs
        ],
    )


def get_recommendations(conn: sqlite3.Connection, user_id: int):
    rows = conn.execute(
        "SELECT artist, track, score, image_url, preview_url FROM recommendations "
        "WHERE user_id = ? ORDER BY score DESC, artist ASC",
        (user_id,),
    ).fetchall()
    return [(a, t, s, img, prev) for (a, t, s, img, prev) in rows]


def get_top_artist_channels(conn: sqlite3.Connection, user_id: int) -> dict:
    rows = conn.execute(
        """
        SELECT channel_title, channel_id FROM liked_videos WHERE user_id = ?
        UNION ALL
        SELECT pi.channel_title, pi.channel_id
        FROM playlist_items pi JOIN playlists p ON p.id = pi.playlist_row_id
        WHERE p.user_id = ? AND pi.category_id = '10'
        """,
        (user_id, user_id),
    ).fetchall()
    mapping: dict = {}
    for channel_title, channel_id in rows:
        if channel_title is None or channel_id is None:
            continue
        mapping.setdefault(normalize_artist(channel_title), channel_id)
    return mapping


def upsert_artist_details(
    conn, artist_name, avatar_url, genre, bio, listeners, album_art_url=None
) -> None:
    conn.execute(
        "INSERT INTO artist_details "
        "(artist_name, avatar_url, genre, bio, listeners, album_art_url) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(artist_name) DO UPDATE SET "
        "avatar_url=excluded.avatar_url, genre=excluded.genre, bio=excluded.bio, "
        "listeners=excluded.listeners, album_art_url=excluded.album_art_url",
        (artist_name, avatar_url, genre, bio, listeners, album_art_url),
    )


def get_artist_details(conn, artist_name) -> dict | None:
    row = conn.execute(
        "SELECT avatar_url, genre, bio, listeners, album_art_url "
        "FROM artist_details WHERE artist_name = ?",
        (artist_name,),
    ).fetchone()
    if row is None:
        return None
    return {
        "avatar_url": row[0],
        "genre": row[1],
        "bio": row[2],
        "listeners": row[3],
        "album_art_url": row[4],
    }


def set_user_syncing(conn, user_id, syncing) -> None:
    conn.execute("UPDATE users SET syncing = ? WHERE id = ?", (1 if syncing else 0, user_id))


def clear_all_syncing(conn) -> None:
    # `syncing` means "a sync is running in this process", so a freshly started
    # process can only be looking at flags left behind by a dead one.
    conn.execute("UPDATE users SET syncing = 0")


def is_sync_ready(conn, user_id) -> bool:
    row = conn.execute("SELECT syncing FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row) and row[0] == 0


def upsert_resolved_song(conn, video_id, artist, track, is_cover, ok) -> None:
    conn.execute(
        "INSERT INTO resolved_songs (video_id, artist, track, is_cover, ok) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(video_id) DO UPDATE SET "
        "artist=excluded.artist, track=excluded.track, "
        "is_cover=excluded.is_cover, ok=excluded.ok",
        (video_id, artist, track, 1 if is_cover else 0, 1 if ok else 0),
    )


def get_unresolved_songs(conn, user_id) -> list[dict]:
    rows = conn.execute(
        """
        SELECT video_id, channel_title, title FROM liked_videos
        WHERE user_id = ?
              AND (channel_title IS NULL OR channel_title NOT LIKE '% - Topic')
        UNION
        SELECT pi.video_id, pi.channel_title, pi.title
        FROM playlist_items pi JOIN playlists p ON p.id = pi.playlist_row_id
        WHERE p.user_id = ? AND pi.category_id = '10'
              AND (pi.channel_title IS NULL OR pi.channel_title NOT LIKE '% - Topic')
        """,
        (user_id, user_id),
    ).fetchall()
    done = {r[0] for r in conn.execute(
        "SELECT video_id FROM resolved_songs"
    ).fetchall()}
    out: list[dict] = []
    seen = set()
    for video_id, channel_title, title in rows:
        if video_id in done or video_id in seen:
            continue
        seen.add(video_id)
        out.append(
            {"video_id": video_id, "channel_title": channel_title, "title": title}
        )
    return out
