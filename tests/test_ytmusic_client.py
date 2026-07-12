# tests/test_ytmusic_client.py
from ytm_taste import ytmusic_client


class FakeClient:
    def __init__(self, account_info):
        self._account_info = account_info

    def get_account_info(self):
        return self._account_info


def test_get_channel_handle_returns_handle_from_account_info():
    client = FakeClient(
        {
            "accountName": "Sample User",
            "channelHandle": "@SampleUser",
            "accountPhotoUrl": "https://example.com/photo.jpg",
        }
    )
    assert ytmusic_client.get_channel_handle(client) == "@SampleUser"


def test_get_channel_handle_returns_none_when_absent():
    client = FakeClient(
        {
            "accountName": "Sample User",
            "channelHandle": None,
            "accountPhotoUrl": "https://example.com/photo.jpg",
        }
    )
    assert ytmusic_client.get_channel_handle(client) is None
