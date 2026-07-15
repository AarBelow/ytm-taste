# src/ytm_taste/google_oauth.py
import json

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def build_flow(
    client_id: str, client_secret: str, redirect_uri: str, code_verifier: str | None = None
) -> Flow:
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    return Flow.from_client_config(
        client_config, scopes=SCOPES, redirect_uri=redirect_uri, code_verifier=code_verifier
    )


def get_authorization_url(flow) -> tuple[str, str, str]:
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    return url, state, flow.code_verifier


def fetch_credentials(flow, authorization_response: str):
    flow.fetch_token(authorization_response=authorization_response)
    return flow.credentials


def credentials_from_json(token_json: str, refresh_fn=None):
    """Rebuild credentials from the token stored at login.

    We ask for offline access, so the stored token carries a refresh_token. That
    lets us re-sync on demand without sending the user back through Google's
    consent screen. Access tokens last about an hour, so refresh when stale.
    """
    creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    if creds.expired and creds.refresh_token:
        if refresh_fn is not None:
            refresh_fn(creds)
        else:
            creds.refresh(Request())
    return creds
