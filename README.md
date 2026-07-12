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

## Logging In and Syncing Your Listening History

This app uses Google login (YouTube Music's own OAuth device flow) instead
of manually copying browser headers, and supports multiple people each
syncing their own separate listening history.

One-time setup, done once by whoever runs this app:

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project (or reuse one), enable the "YouTube Data API v3", then create
   OAuth credentials of type **"TVs and Limited Input devices"**. Copy the
   resulting Client ID and Client Secret.
2. Copy `.env.example` to `.env` and fill in:
   ```
   GOOGLE_OAUTH_CLIENT_ID=<your client id>
   GOOGLE_OAUTH_CLIENT_SECRET=<your client secret>
   SECRET_KEY=<any random string, used to sign login session cookies>
   ```
3. In that same OAuth client's consent screen, add each person's Google
   account email as a **test user** before they can log in — required
   while the app is unverified (fine for a handful of friends; capped at
   100 test users total).

Then run the server:
```
uvicorn ytm_taste.main:app --app-dir src --reload
```
Visit http://127.0.0.1:8000/login, click through to Google, and approve
access — your listening history starts syncing automatically in the
background. Revisiting `/login` later re-syncs your data without creating
a duplicate account.

## Roadmap

1. **Project scaffolding** — folder structure, FastAPI hello-world, venv, tests wired up (this phase)
2. **YTM data fetch + SQLite storage** — pull listening history via `ytmusicapi`, persist to SQLite
3. **Last.fm genre enrichment** — tag artists with genres via the Last.fm API
4. **Taste profile building** — top genres, top artists, listening patterns
5. **Artist recommendations** — suggest new artists based on the taste profile
6. **YTMDesktop playback control** — control playback via the YTMDesktop Companion Server API (`localhost:9863`)
7. **Frontend polish** — HTML/JS UI served by the FastAPI backend
