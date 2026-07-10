# ytm-taste

Personal YouTube Music taste analyzer and remote controller.

Fetches your YouTube Music listening history, enriches artists with genre
tags from Last.fm, stores everything in SQLite, and builds a taste profile
(top genres, top artists, listening patterns). Runs locally as a small
FastAPI + HTML/JS web app you open in your browser.

## Setup

1. Create a virtual environment:
   ```
   py -m venv .venv
   ```
2. Activate it (PowerShell):
   ```
   .venv\Scripts\Activate.ps1
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in your Last.fm API credentials:
   ```
   copy .env.example .env
   ```
5. Run the server:
   ```
   uvicorn ytm_taste.main:app --app-dir src --reload
   ```
   Visit http://127.0.0.1:8000 — you should see `{"status": "ok", "service": "ytm-taste"}`.
6. Run the tests:
   ```
   pytest
   ```

## Fetching Your Listening History

One-time setup — generate a YouTube Music auth file (requires pasting request
headers copied from your browser while logged into music.youtube.com; this
step is interactive and must be run by you, not automated):
```
.venv\Scripts\ytmusicapi.exe browser --file ytmusic_auth.json
```

Then, whenever you want to pull your latest listening history into the
database:
```
python -m ytm_taste.sync
```

Each run adds new observations to `data/ytm_taste.db` without erasing
anything already stored — safe to run repeatedly (e.g. weekly) to build up
history over time.

## Roadmap

1. **Project scaffolding** — folder structure, FastAPI hello-world, venv, tests wired up (this phase)
2. **YTM data fetch + SQLite storage** — pull listening history via `ytmusicapi`, persist to SQLite
3. **Last.fm genre enrichment** — tag artists with genres via the Last.fm API
4. **Taste profile building** — top genres, top artists, listening patterns
5. **Artist recommendations** — suggest new artists based on the taste profile
6. **YTMDesktop playback control** — control playback via the YTMDesktop Companion Server API (`localhost:9863`)
7. **Frontend polish** — HTML/JS UI served by the FastAPI backend
