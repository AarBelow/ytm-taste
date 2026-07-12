# tests/test_google_oauth.py
from ytm_taste import google_oauth


def test_build_flow_wires_client_id_secret_and_redirect_uri():
    flow = google_oauth.build_flow(
        "client-id", "client-secret", "http://127.0.0.1:8000/auth/callback"
    )
    # Note: the installed google-auth-oauthlib (1.4.0) stores client_config as
    # the flattened inner dict (e.g. the "web" sub-dict), not wrapped in
    # {"web": {...}} as in some other versions. This still verifies that
    # build_flow wires client_id/client_secret/redirect_uri into the real
    # Flow object correctly.
    assert flow.client_config["client_id"] == "client-id"
    assert flow.client_config["client_secret"] == "client-secret"
    assert flow.redirect_uri == "http://127.0.0.1:8000/auth/callback"


class FakeFlow:
    def __init__(self):
        self.authorization_url_calls = []
        self.fetch_token_calls = []
        self.credentials = "fake-credentials"

    def authorization_url(self, **kwargs):
        self.authorization_url_calls.append(kwargs)
        return "https://accounts.google.com/fake-auth-url", "fake-state"

    def fetch_token(self, **kwargs):
        self.fetch_token_calls.append(kwargs)


def test_get_authorization_url_requests_offline_access_and_consent_prompt():
    flow = FakeFlow()
    url, state = google_oauth.get_authorization_url(flow)
    assert url == "https://accounts.google.com/fake-auth-url"
    assert state == "fake-state"
    assert flow.authorization_url_calls == [{"access_type": "offline", "prompt": "consent"}]


def test_fetch_credentials_passes_callback_url_and_returns_credentials():
    flow = FakeFlow()
    callback_url = "http://127.0.0.1:8000/auth/callback?code=abc&state=fake-state"
    result = google_oauth.fetch_credentials(flow, callback_url)
    assert result == "fake-credentials"
    assert flow.fetch_token_calls == [{"authorization_response": callback_url}]
