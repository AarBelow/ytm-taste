# src/ytm_taste/db.py
import json
import sqlite3
from collections import Counter

# Fine-tune preferences. "playlists" empty means "all my music".
DEFAULT_PREFS = {"playlists": [], "discovery": "mix", "mode": "safe"}

# A playlist needs at least this many nameable songs to be worth seeding from -- a
# 3-song playlist would give 3 seeds and a threadbare set of recommendations.
MIN_SEEDABLE_PLAYLIST = 8

# Last.fm's catalogue comes from scrobbles, so a mis-split title like "05" or
# "平行線" can still "exist" with a few hundred listeners. Seeds tolerate that (a
# wrong seed is cheap), but crediting a fake artist on the top-artists page is
# loud, so credit requires real popularity. Measured against the live library:
# junk resolutions topped out ~260 listeners; genuine artists cleared thousands.
MIN_CREDIT_LISTENERS = 2000

# Only the most recent liked songs seed recommendations, so suggestions track what
# you're into lately. Playlists are never capped. YouTube returns likes newest-first
# (observed, not documented), so insertion order is recency order.
RECENT_LIKED_SEEDS = 50


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

        CREATE TABLE IF NOT EXISTS silent_seeds (
            artist TEXT NOT NULL,
            track TEXT NOT NULL,
            PRIMARY KEY (artist, track)
        );

        CREATE TABLE IF NOT EXISTS resolved_songs (
            video_id TEXT PRIMARY KEY,
            artist TEXT,
            track TEXT,
            is_cover INTEGER NOT NULL DEFAULT 0,
            ok INTEGER NOT NULL,
            listeners INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    rcols = [r[1] for r in conn.execute("PRAGMA table_info(resolved_songs)").fetchall()]
    if "listeners" not in rcols:
        conn.execute("ALTER TABLE resolved_songs ADD COLUMN listeners INTEGER NOT NULL DEFAULT 0")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(artist_details)").fetchall()]
    if "album_art_url" not in cols:
        conn.execute("ALTER TABLE artist_details ADD COLUMN album_art_url TEXT")
    ucols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "syncing" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN syncing INTEGER NOT NULL DEFAULT 0")
    if "prefs" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN prefs TEXT")
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


def _resolved_for_user(conn, user_id) -> list[tuple[str, str, str, int, int]]:
    """(video_id, artist, track, is_cover, listeners) for this user's resolved songs."""
    return conn.execute(
        """
        SELECT rs.video_id, rs.artist, rs.track, rs.is_cover, rs.listeners FROM resolved_songs rs
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
        vid: (artist, is_cover, listeners)
        for vid, artist, _track, is_cover, listeners in _resolved_for_user(conn, user_id)
    }
    # Counted case-insensitively: YouTube's Topic channel ("Kaz Moon") and Last.fm's
    # canonical spelling ("kaz moon") are the same artist and must not split in two.
    counts: Counter = Counter()
    spellings: dict[str, Counter] = {}

    def credit(name: str) -> None:
        key = name.casefold()
        counts[key] += 1
        spellings.setdefault(key, Counter())[name] += 1

    for video_id, channel_title in rows:
        if channel_title and channel_title.endswith(" - Topic"):
            credit(normalize_artist(channel_title))
            continue
        entry = resolved.get(video_id)
        if entry is None:
            continue  # unverified: no credit
        artist, is_cover, listeners = entry
        if is_cover or not artist:
            continue  # covers seed but never get credit
        if listeners < MIN_CREDIT_LISTENERS:
            continue  # too obscure to trust as an artist name; it still seeds
        credit(artist)
    # Display the spelling we saw most often for each artist.
    named = [(spellings[key].most_common(1)[0][0], count) for key, count in counts.items()]
    return sorted(named, key=lambda kv: (-kv[1], kv[0]))


def get_clean_seed_songs(
    conn: sqlite3.Connection, user_id: int, playlist_ids=None
) -> list[tuple[str, str]]:
    # When the user picks specific playlists they've chosen a context ("I miss her"),
    # so liked songs are excluded -- mixing them back in would dilute the choice.
    if playlist_ids:
        marks = ",".join("?" for _ in playlist_ids)
        rows = conn.execute(
            f"""
            SELECT pi.video_id, pi.channel_title, pi.title
            FROM playlist_items pi
            JOIN playlists p ON p.id = pi.playlist_row_id
            WHERE p.user_id = ? AND pi.category_id = '10' AND p.playlist_id IN ({marks})
            """,
            (user_id, *playlist_ids),
        ).fetchall()
        rows = list(rows)
        eligible = {video_id for video_id, _c, _t in rows}
        return _seeds_from(conn, user_id, rows, eligible)

    liked = conn.execute(
        "SELECT video_id, channel_title, title FROM liked_videos "
        "WHERE user_id = ? ORDER BY id LIMIT ?",
        (user_id, RECENT_LIKED_SEEDS),
    ).fetchall()
    playlist = conn.execute(
        """
        SELECT pi.video_id, pi.channel_title, pi.title
        FROM playlist_items pi
        JOIN playlists p ON p.id = pi.playlist_row_id
        WHERE p.user_id = ? AND pi.category_id = '10'
        """,
        (user_id,),
    ).fetchall()
    rows = list(liked) + list(playlist)
    eligible = {video_id for video_id, _channel, _title in rows}
    return _seeds_from(conn, user_id, rows, eligible)


def _seeds_from(conn, user_id, rows, eligible) -> list[tuple[str, str]]:
    """Nameable (artist, track) pairs from the given rows: '- Topic' channels name
    themselves, everything else needs a resolution. Deduped, since a song that is both
    liked and in a playlist must not take two seed slots."""
    seeds: list[tuple[str, str]] = []
    for _video_id, channel_title, title in rows:
        if channel_title and channel_title.endswith(" - Topic"):
            seeds.append((normalize_artist(channel_title), title))
    for video_id, artist, track, _is_cover, _listeners in _resolved_for_user(conn, user_id):
        if artist and track and video_id in eligible:
            seeds.append((artist, track))

    silent = get_silent_seeds(conn)
    deduped: list[tuple[str, str]] = []
    seen = set()
    for artist, track in seeds:
        key = (artist.casefold(), track.casefold())
        if key in seen or key in silent:
            continue  # duplicates take two slots; silent seeds cast no votes at all
        seen.add(key)
        deduped.append((artist, track))
    return deduped


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
    for _vid, artist, track, _is_cover, _listeners in _resolved_for_user(conn, user_id):
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


def get_library_stats(conn: sqlite3.Connection, user_id: int) -> dict:
    """Headline counts for the landing page once a user has synced: how many distinct
    tracks were analyzed, how many artists were ranked, and how many recommendations
    are currently on offer."""
    tracks = len(get_owned_song_keys(conn, user_id))
    artists = len(get_top_artists(conn, user_id))
    recs = conn.execute(
        "SELECT COUNT(*) FROM recommendations WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    return {"tracks": tracks, "artists": artists, "recs": recs}


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


def mark_silent_seeds(conn, pairs) -> None:
    """Remember songs Last.fm returns no similar tracks for.

    Such a seed casts zero votes: it burns a slot and teaches nothing. Measured on the
    real library, 46 of 100 seeds were silent -- including 16 of the 27 given to the
    top artist by quota. Skipping them lets the budget go to songs that can speak.
    """
    conn.executemany(
        "INSERT OR IGNORE INTO silent_seeds (artist, track) VALUES (?, ?)",
        [(artist.casefold(), track.casefold()) for artist, track in pairs],
    )


def get_silent_seeds(conn) -> set[tuple[str, str]]:
    return {(a, t) for a, t in conn.execute("SELECT artist, track FROM silent_seeds").fetchall()}


def set_user_prefs(conn, user_id, prefs: dict) -> None:
    conn.execute("UPDATE users SET prefs = ? WHERE id = ?", (json.dumps(prefs), user_id))


def get_user_prefs(conn, user_id) -> dict:
    row = conn.execute("SELECT prefs FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or not row[0]:
        return dict(DEFAULT_PREFS)
    try:
        stored = json.loads(row[0])
    except (ValueError, TypeError):
        return dict(DEFAULT_PREFS)
    if not isinstance(stored, dict):
        return dict(DEFAULT_PREFS)
    return {**DEFAULT_PREFS, **stored}


def get_seedable_playlists(conn, user_id) -> list[dict]:
    """Playlists with enough nameable songs to seed from, biggest first."""
    resolved = {
        r[0] for r in conn.execute("SELECT video_id FROM resolved_songs WHERE ok = 1").fetchall()
    }
    out = []
    rows = conn.execute(
        "SELECT id, playlist_id, title FROM playlists WHERE user_id = ?", (user_id,)
    ).fetchall()
    for row_id, playlist_id, title in rows:
        items = conn.execute(
            "SELECT video_id, channel_title FROM playlist_items "
            "WHERE playlist_row_id = ? AND category_id = '10'",
            (row_id,),
        ).fetchall()
        count = sum(
            1
            for video_id, channel in items
            if (channel and channel.endswith(" - Topic")) or video_id in resolved
        )
        if count >= MIN_SEEDABLE_PLAYLIST:
            out.append({"playlist_id": playlist_id, "title": title, "count": count})
    return sorted(out, key=lambda p: (-p["count"], p["title"]))


def clear_all_syncing(conn) -> None:
    # `syncing` means "a sync is running in this process", so a freshly started
    # process can only be looking at flags left behind by a dead one.
    conn.execute("UPDATE users SET syncing = 0")


def user_exists(conn, user_id) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is not None


def is_sync_ready(conn, user_id) -> bool:
    row = conn.execute("SELECT syncing FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row) and row[0] == 0


def upsert_resolved_song(conn, video_id, artist, track, is_cover, ok, listeners=0) -> None:
    conn.execute(
        "INSERT INTO resolved_songs (video_id, artist, track, is_cover, ok, listeners) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(video_id) DO UPDATE SET "
        "artist=excluded.artist, track=excluded.track, "
        "is_cover=excluded.is_cover, ok=excluded.ok, listeners=excluded.listeners",
        (video_id, artist, track, 1 if is_cover else 0, 1 if ok else 0, int(listeners or 0)),
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
