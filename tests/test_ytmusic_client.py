import pytest

from ytm_taste import ytmusic_client


def test_get_client_raises_clear_error_when_auth_file_missing(tmp_path):
    missing_path = str(tmp_path / "does_not_exist.json")
    with pytest.raises(RuntimeError, match="ytmusicapi browser"):
        ytmusic_client.get_client(missing_path)
