from ytm_taste import oauth_device_flow


class FakeCredentials:
    def __init__(self, code_response=None, token_responses=None):
        self._code_response = code_response or {
            "device_code": "devcode123",
            "user_code": "ABC-DEF",
            "verification_url": "https://www.google.com/device",
            "expires_in": 1800,
            "interval": 5,
        }
        self._token_responses = list(token_responses or [])

    def get_code(self):
        return self._code_response

    def token_from_code(self, device_code):
        return self._token_responses.pop(0)


def test_start_flow_builds_prefilled_url_and_state():
    creds = FakeCredentials()
    state = oauth_device_flow.start_flow(creds)
    assert state.device_code == "devcode123"
    assert state.verification_url_complete == "https://www.google.com/device?user_code=ABC-DEF"
    assert state.interval == 5


def test_check_flow_pending():
    creds = FakeCredentials(token_responses=[{"error": "authorization_pending"}])
    result = oauth_device_flow.check_flow(creds, "devcode123")
    assert result.status == "pending"


def test_check_flow_slow_down_treated_as_pending():
    creds = FakeCredentials(token_responses=[{"error": "slow_down"}])
    result = oauth_device_flow.check_flow(creds, "devcode123")
    assert result.status == "pending"


def test_check_flow_done():
    token = {
        "access_token": "tok123",
        "refresh_token": "ref123",
        "scope": "https://www.googleapis.com/auth/youtube",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    creds = FakeCredentials(token_responses=[token])
    result = oauth_device_flow.check_flow(creds, "devcode123")
    assert result.status == "done"
    assert result.token == token


def test_check_flow_expired():
    creds = FakeCredentials(token_responses=[{"error": "expired_token"}])
    result = oauth_device_flow.check_flow(creds, "devcode123")
    assert result.status == "expired"


def test_check_flow_denied():
    creds = FakeCredentials(token_responses=[{"error": "access_denied"}])
    result = oauth_device_flow.check_flow(creds, "devcode123")
    assert result.status == "denied"


def test_check_flow_unrecognized_error():
    creds = FakeCredentials(token_responses=[{"error": "something_else"}])
    result = oauth_device_flow.check_flow(creds, "devcode123")
    assert result.status == "error"
