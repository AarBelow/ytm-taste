# src/ytm_taste/db.py
import sqlite3


def get_connection(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT UNIQUE NOT NULL,
            oauth_token TEXT NOT NULL,
            created_at TEXT NOT NULL
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
            channel_title TEXT NOT NULL
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
            title TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            channel_id TEXT NOT NULL,
            channel_title TEXT NOT NULL
        );
        """
    )
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
        "INSERT INTO liked_videos (user_id, video_id, title, channel_title) VALUES (?, ?, ?, ?)",
        [(user_id, v["video_id"], v["title"], v["channel_title"]) for v in videos],
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
            "INSERT INTO playlist_items (playlist_row_id, video_id, title) VALUES (?, ?, ?)",
            [(playlist_row_id, item["video_id"], item["title"]) for item in items],
        )


def replace_subscriptions(
    conn: sqlite3.Connection, user_id: int, subscriptions: list[dict]
) -> None:
    conn.execute("DELETE FROM subscriptions WHERE user_id = ?", (user_id,))
    conn.executemany(
        "INSERT INTO subscriptions (user_id, channel_id, channel_title) VALUES (?, ?, ?)",
        [(user_id, s["channel_id"], s["channel_title"]) for s in subscriptions],
    )


def get_top_artists(conn: sqlite3.Connection, user_id: int) -> list[tuple[str, int]]:
    rows = conn.execute(
        """
        SELECT channel_title, COUNT(*) AS liked_count
        FROM liked_videos
        WHERE user_id = ?
        GROUP BY channel_title
        ORDER BY liked_count DESC, channel_title ASC
        """,
        (user_id,),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]
