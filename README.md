# ytm-taste

Personal YouTube Music taste analyzer and remote controller.

Fetches your YouTube liked videos, playlists, and subscriptions via the
official YouTube Data API, enriches artists with genre tags from Last.fm
(planned), stores everything in SQLite, and builds a taste profile (top
genres, top artists, listening patterns). Runs locally as a small
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

## Logging In and Syncing Your YouTube Data

This app uses standard "Login with Google" (the official YouTube Data API
v3), and supports multiple people each syncing their own separate data:
liked videos (filtered to actual music), playlists (with contents), and
channel subscriptions.

One-time setup, done once by whoever runs this app:

1. In [Google Cloud Console](https://console.cloud.google.com/), reuse the
   project from before (or create one, enabling "YouTube Data API v3"), then
   create OAuth credentials of type **"Web application"**. Add
   `http://127.0.0.1:8000/auth/callback` as an **Authorized redirect URI**.
   Copy the resulting Client ID and Client Secret.
2. In that project's OAuth consent screen, under **Data Access**, make sure
   the `https://www.googleapis.com/auth/youtube.readonly` scope is added.
3. Copy `.env.example` to `.env` and fill in:
   ```
   GOOGLE_WEB_CLIENT_ID=<your web client id>
   GOOGLE_WEB_CLIENT_SECRET=<your web client secret>
   SECRET_KEY=<any random string, used to sign login session cookies>
   ```
   (`GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET` are left over from
   an earlier, now-unused device-flow login attempt and can stay blank.)
4. In that same OAuth client's consent screen, add each person's Google
   account email as a **test user** before they can log in — required
   while the app is unverified (fine for a handful of friends; capped at
   100 test users total).

Then run the server:
```
uvicorn ytm_taste.main:app --app-dir src --reload
```
Visit http://127.0.0.1:8000/login, approve access on Google's page, and
you'll be redirected back — your liked videos, playlists, and
subscriptions start syncing automatically in the background. Revisiting
`/login` later re-syncs your data without creating a duplicate account.

## Roadmap

1. **Project scaffolding** — folder structure, FastAPI hello-world, venv, tests wired up (this phase)
2. **YouTube data fetch + SQLite storage** — pull liked videos, playlists, and subscriptions via the official YouTube Data API, persist to SQLite
3. **Last.fm genre enrichment** — tag artists with genres via the Last.fm API
4. **Taste profile building** — top genres, top artists, listening patterns
5. **Artist recommendations** — suggest new artists based on the taste profile
6. **YTMDesktop playback control** — control playback via the YTMDesktop Companion Server API (`localhost:9863`)
7. **Frontend polish** — HTML/JS UI served by the FastAPI backend
