# src/ytm_taste/main.py
import os
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


@app.get("/")
def read_root():
    return {"status": "ok", "service": "ytm-taste"}


def _build_flow():
    return google_oauth.build_flow(
        os.environ["GOOGLE_WEB_CLIENT_ID"],
        os.environ["GOOGLE_WEB_CLIENT_SECRET"],
        REDIRECT_URI,
    )


@app.get("/login")
def login(request: Request):
    flow = _build_flow()
    authorization_url, state = google_oauth.get_authorization_url(flow)
    request.session["oauth_state"] = state
    return RedirectResponse(authorization_url)


@app.get("/auth/callback", response_class=HTMLResponse)
def auth_callback(request: Request, background_tasks: BackgroundTasks):
    state = request.query_params.get("state")
    if state is None or state != request.session.get("oauth_state"):
        return HTMLResponse("Login failed: invalid or expired login attempt.", status_code=400)
    request.session.pop("oauth_state", None)

    flow = _build_flow()
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
    background_tasks.add_task(sync.run_sync, DB_PATH, user_id, youtube)

    return RedirectResponse("/")
