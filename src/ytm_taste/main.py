# src/ytm_taste/main.py
import json
import os
import secrets
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from ytmusicapi.auth.oauth import OAuthCredentials

from ytm_taste import db, oauth_device_flow, sync, ytmusic_client

load_dotenv()

app = FastAPI(title="ytm-taste")
app.add_middleware(SessionMiddleware, secret_key=os.environ["SECRET_KEY"])

_credentials = OAuthCredentials(
    client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
)

_pending_flows: dict[str, dict] = {}

DB_PATH = "data/ytm_taste.db"


@app.get("/")
def read_root():
    return {"status": "ok", "service": "ytm-taste"}


def render_login_page(flow_id: str, verification_url_complete: str, interval: int) -> str:
    config = json.dumps(
        {
            "flowId": flow_id,
            "verificationUrl": verification_url_complete,
            "intervalMs": interval * 1000,
        }
    )
    return f"""<!DOCTYPE html>
<html>
<head><title>Login</title></head>
<body>
<p>Click below, then approve access on Google's page:</p>
<a id="google-link" href="#" target="_blank">Continue to Google</a>
<p id="status">Waiting for approval...</p>
<script>
const config = {config};
document.getElementById("google-link").href = config.verificationUrl;
async function poll() {{
    const res = await fetch("/login/status?flow_id=" + config.flowId);
    const data = await res.json();
    if (data.status === "pending") {{
        setTimeout(poll, config.intervalMs);
    }} else if (data.status === "done") {{
        document.getElementById("status").textContent = "Logged in! Redirecting...";
        window.location.href = data.redirect;
    }} else {{
        document.getElementById("status").textContent = "Error: " + data.message;
    }}
}}
setTimeout(poll, config.intervalMs);
</script>
</body>
</html>"""


@app.get("/login", response_class=HTMLResponse)
def login():
    state = oauth_device_flow.start_flow(_credentials)
    flow_id = secrets.token_urlsafe(16)
    _pending_flows[flow_id] = {
        "device_code": state.device_code,
        "expires_at": state.expires_at,
    }
    return render_login_page(flow_id, state.verification_url_complete, state.interval)


@app.get("/login/status")
def login_status(flow_id: str, request: Request, background_tasks: BackgroundTasks):
    flow = _pending_flows.get(flow_id)
    if flow is None:
        return JSONResponse({"status": "error", "message": "Unknown or expired login attempt."})

    if time.monotonic() > flow["expires_at"]:
        del _pending_flows[flow_id]
        return JSONResponse(
            {"status": "error", "message": "The login code expired. Please try again."}
        )

    result = oauth_device_flow.check_flow(_credentials, flow["device_code"])

    if result.status == "pending":
        return JSONResponse({"status": "pending"})

    if result.status in ("expired", "denied", "error"):
        del _pending_flows[flow_id]
        return JSONResponse({"status": "error", "message": result.message})

    del _pending_flows[flow_id]
    client = ytmusic_client.get_client_from_oauth(result.token, _credentials)
    channel_handle = ytmusic_client.get_channel_handle(client)
    if channel_handle is None:
        return JSONResponse(
            {
                "status": "error",
                "message": (
                    "Your YouTube account needs a public handle set up "
                    "before you can use this app."
                ),
            }
        )

    conn = db.get_connection(DB_PATH)
    db.init_db(conn)
    now = datetime.now(timezone.utc).isoformat()
    user_id = db.get_or_create_user(conn, channel_handle, json.dumps(result.token), now)
    conn.commit()
    conn.close()

    request.session["user_id"] = user_id
    background_tasks.add_task(sync.run_sync, DB_PATH, user_id, client)

    return JSONResponse({"status": "done", "redirect": "/"})
