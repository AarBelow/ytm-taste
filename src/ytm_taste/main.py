# src/ytm_taste/main.py
import html
import os
import urllib.parse
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from ytm_taste import db, google_oauth, sync, youtube_client

load_dotenv()

# This app's redirect URI is plain HTTP (http://127.0.0.1:8000/auth/callback)
# since it's local-only by design (no deployment/hosting this cycle). Google's
# oauthlib refuses to process a non-HTTPS authorization_response URL unless
# this is set — the standard, documented approach for local OAuth development.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

app = FastAPI(title="ytm-taste")
app.add_middleware(SessionMiddleware, secret_key=os.environ["SECRET_KEY"])

REDIRECT_URI = "http://127.0.0.1:8000/auth/callback"

DB_PATH = "data/ytm_taste.db"


@app.get("/health")
def health():
    return {"status": "ok", "service": "ytm-taste"}


def render_results_page(artists: list[tuple[str, int]]) -> str:
    if not artists:
        body = (
            '<p class="empty">No liked music synced yet — if you just logged in, '
            "give it a few seconds and refresh.</p>"
        )
    else:
        items = "\n".join(
            f'<li><span class="rank">{i}</span>'
            f'<span class="artist">{html.escape(name)}</span>'
            f'<span class="count">{count}</span></li>'
            for i, (name, count) in enumerate(artists, start=1)
        )
        body = f'<ol class="artists">{items}</ol>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Your Top Artists</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 640px;
         margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.5rem; }}
  ol.artists {{ list-style: none; padding: 0; }}
  ol.artists li {{ display: flex; align-items: baseline; gap: 0.75rem;
                   padding: 0.35rem 0; border-bottom: 1px solid #8883; }}
  .rank {{ width: 2rem; text-align: right; opacity: 0.6; }}
  .artist {{ flex: 1; }}
  .count {{ opacity: 0.7; font-variant-numeric: tabular-nums; }}
  .empty {{ opacity: 0.7; }}
</style>
</head>
<body>
<h1>Your Top Artists</h1>
<p><a href="/recommendations">Songs you might like &rarr;</a></p>
{body}
</body>
</html>"""


def render_recommendations_page(recs: list[tuple[str, str, float]]) -> str:
    if not recs:
        body = (
            '<p class="empty">No recommendations yet — after you log in, the sync '
            "generates them in the background; give it a moment and refresh.</p>"
        )
    else:
        items = "\n".join(
            f'<li><span class="artist">{html.escape(artist)}</span>'
            f'<span class="track">{html.escape(track)}</span>'
            f'<a class="yt" target="_blank" '
            f'href="https://www.youtube.com/results?search_query='
            f'{urllib.parse.quote(artist + " " + track)}">search</a></li>'
            for artist, track, _score in recs
        )
        body = f'<ol class="recs">{items}</ol>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Songs You Might Like</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 640px;
         margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.5rem; }}
  ol.recs {{ list-style: none; padding: 0; }}
  ol.recs li {{ display: flex; align-items: baseline; gap: 0.75rem;
                padding: 0.35rem 0; border-bottom: 1px solid #8883; }}
  .artist {{ font-weight: 600; }}
  .track {{ flex: 1; opacity: 0.85; }}
  .empty {{ opacity: 0.7; }}
</style>
</head>
<body>
<h1>Songs You Might Like</h1>
<p><a href="/">&larr; back to your top artists</a></p>
{body}
</body>
</html>"""


@app.get("/")
def read_root(request: Request):
    user_id = request.session.get("user_id")
    if user_id is None:
        return RedirectResponse("/login")
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    artists = db.get_top_artists(conn, user_id)
    conn.close()
    return HTMLResponse(render_results_page(artists))


@app.get("/recommendations")
def recommendations_page(request: Request):
    user_id = request.session.get("user_id")
    if user_id is None:
        return RedirectResponse("/login")
    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    recs = db.get_recommendations(conn, user_id)
    conn.close()
    return HTMLResponse(render_recommendations_page(recs))


def _build_flow(code_verifier: str | None = None):
    return google_oauth.build_flow(
        os.environ["GOOGLE_WEB_CLIENT_ID"],
        os.environ["GOOGLE_WEB_CLIENT_SECRET"],
        REDIRECT_URI,
        code_verifier=code_verifier,
    )


@app.get("/login")
def login(request: Request):
    flow = _build_flow()
    authorization_url, state, code_verifier = google_oauth.get_authorization_url(flow)
    request.session["oauth_state"] = state
    request.session["oauth_code_verifier"] = code_verifier
    return RedirectResponse(authorization_url)


@app.get("/auth/callback", response_class=HTMLResponse)
def auth_callback(request: Request, background_tasks: BackgroundTasks):
    state = request.query_params.get("state")
    if state is None or state != request.session.get("oauth_state"):
        return HTMLResponse("Login failed: invalid or expired login attempt.", status_code=400)
    code_verifier = request.session.get("oauth_code_verifier")
    request.session.pop("oauth_state", None)
    request.session.pop("oauth_code_verifier", None)

    flow = _build_flow(code_verifier=code_verifier)
    credentials = google_oauth.fetch_credentials(flow, str(request.url))
    youtube = youtube_client.build_youtube_client(credentials)
    channel_id = youtube_client.get_channel_id(youtube)
    if channel_id is None:
        return HTMLResponse(
            "Login failed: your YouTube account needs a channel before you can use this app.",
            status_code=400,
        )

    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    now = datetime.now(timezone.utc).isoformat()
    user_id = db.get_or_create_user(conn, channel_id, credentials.to_json(), now)
    conn.commit()
    conn.close()

    request.session["user_id"] = user_id
    background_tasks.add_task(
        sync.run_sync, DB_PATH, user_id, youtube,
        lastfm_api_key=os.environ.get("LASTFM_API_KEY"),
    )

    return RedirectResponse("/")
