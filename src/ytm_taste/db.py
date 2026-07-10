import sqlite3


def get_connection(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tracks (
            video_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            duration_seconds INTEGER,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS artists (
            artist_id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS track_artists (
            video_id TEXT NOT NULL REFERENCES tracks(video_id),
            artist_id TEXT NOT NULL REFERENCES artists(artist_id),
            position INTEGER NOT NULL,
            PRIMARY KEY (video_id, artist_id)
        );

        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            items_fetched INTEGER
        );

        CREATE TABLE IF NOT EXISTS history_snapshot_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_run_id INTEGER NOT NULL REFERENCES sync_runs(id),
            video_id TEXT NOT NULL REFERENCES tracks(video_id),
            position INTEGER NOT NULL,
            played_bucket TEXT
        );
        """
    )
    conn.commit()


def upsert_track(
    conn: sqlite3.Connection,
    video_id: str,
    title: str,
    duration_seconds: int | None,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO tracks (video_id, title, duration_seconds, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET last_seen_at = excluded.last_seen_at
        """,
        (video_id, title, duration_seconds, now, now),
    )


def upsert_artist(conn: sqlite3.Connection, artist_id: str, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO artists (artist_id, name) VALUES (?, ?)",
        (artist_id, name),
    )


def link_track_artist(
    conn: sqlite3.Connection, video_id: str, artist_id: str, position: int
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO track_artists (video_id, artist_id, position) VALUES (?, ?, ?)",
        (video_id, artist_id, position),
    )


def start_sync_run(conn: sqlite3.Connection, started_at: str) -> int:
    cur = conn.execute("INSERT INTO sync_runs (started_at) VALUES (?)", (started_at,))
    return cur.lastrowid


def finish_sync_run(
    conn: sqlite3.Connection, sync_run_id: int, finished_at: str, items_fetched: int
) -> None:
    conn.execute(
        "UPDATE sync_runs SET finished_at = ?, items_fetched = ? WHERE id = ?",
        (finished_at, items_fetched, sync_run_id),
    )


def record_history_entry(
    conn: sqlite3.Connection,
    sync_run_id: int,
    video_id: str,
    position: int,
    played_bucket: str | None,
) -> None:
    conn.execute(
        "INSERT INTO history_snapshot_entries "
        "(sync_run_id, video_id, position, played_bucket) VALUES (?, ?, ?, ?)",
        (sync_run_id, video_id, position, played_bucket),
    )
