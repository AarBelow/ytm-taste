# src/ytm_taste/google_oauth.py
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
