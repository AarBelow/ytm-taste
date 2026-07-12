# tests/test_main.py
from fastapi.testclient import TestClient

from ytm_taste import main, oauth_device_flow, ytmusic_client


def test_read_root():
    client = TestClient(main.app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ytm-taste"}


def make_test_client():
    main._pending_flows.clear()
    return TestClient(main.app)


def test_login_page_contains_flow_id_and_prefilled_link(monkeypatch):
    monkeypatch.setattr(
        oauth_device_flow,
        "start_flow",
        lambda credentials: oauth_device_flow.FlowState(
            device_code="devcode1",
            verification_url_complete="https://www.google.com/device?user_code=ABC-DEF",
            interval=5,
            expires_at=99999999999.0,
        ),
    )
    client = make_test_client()
    response = client.get("/login")
    assert response.status_code == 200
    assert "https://www.google.com/device?user_code=ABC-DEF" in response.text
    assert len(main._pending_flows) == 1


def test_login_status_pending_does_not_set_session(monkeypatch):
    monkeypatch.setattr(
        oauth_device_flow,
        "check_flow",
        lambda credentials, device_code: oauth_device_flow.FlowResult(status="pending"),
    )
    client = make_test_client()
    main._pending_flows["flow1"] = {"device_code": "devcode1", "expires_at": 99999999999.0}

    response = client.get("/login/status", params={"flow_id": "flow1"})
    assert response.json() == {"status": "pending"}
    assert "session" not in response.cookies


def test_login_status_done_creates_user_and_triggers_sync(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "test.db"))

    fake_token = {"access_token": "tok", "refresh_token": "ref"}
    monkeypatch.setattr(
        oauth_device_flow,
        "check_flow",
        lambda credentials, device_code: oauth_device_flow.FlowResult(
            status="done", token=fake_token
        ),
    )
    monkeypatch.setattr(ytmusic_client, "get_client_from_oauth", lambda token, credentials: object())
    monkeypatch.setattr(ytmusic_client, "get_channel_handle", lambda client: "@testuser")

    calls = []

    def fake_run_sync(db_path, user_id, client, **kwargs):
        calls.append((db_path, user_id))
        return {"items_fetched": 0, "new_tracks": 0, "elapsed_seconds": 0.0}

    monkeypatch.setattr(main.sync, "run_sync", fake_run_sync)

    client = make_test_client()
    main._pending_flows["flow1"] = {"device_code": "devcode1", "expires_at": 99999999999.0}

    response = client.get("/login/status", params={"flow_id": "flow1"})
    body = response.json()
    assert body == {"status": "done", "redirect": "/"}
    assert "flow1" not in main._pending_flows
    assert len(calls) == 1
    assert calls[0][0] == str(tmp_path / "test.db")

    from ytm_taste import db as db_module

    conn = db_module.get_connection(str(tmp_path / "test.db"))
    row = conn.execute("SELECT channel_handle FROM users").fetchone()
    assert row == ("@testuser",)


def test_login_status_done_without_handle_does_not_create_user(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DB_PATH", str(tmp_path / "test.db"))

    fake_token = {"access_token": "tok", "refresh_token": "ref"}
    monkeypatch.setattr(
        oauth_device_flow,
        "check_flow",
        lambda credentials, device_code: oauth_device_flow.FlowResult(
            status="done", token=fake_token
        ),
    )
    monkeypatch.setattr(ytmusic_client, "get_client_from_oauth", lambda token, credentials: object())
    monkeypatch.setattr(ytmusic_client, "get_channel_handle", lambda client: None)

    client = make_test_client()
    main._pending_flows["flow1"] = {"device_code": "devcode1", "expires_at": 99999999999.0}

    response = client.get("/login/status", params={"flow_id": "flow1"})
    body = response.json()
    assert body["status"] == "error"
