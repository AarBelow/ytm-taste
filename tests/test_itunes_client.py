# tests/test_itunes_client.py
from ytm_taste import itunes_client


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def make_get(data, calls=None):
    def fake_get(url, params=None, timeout=None):
        if calls is not None:
            calls.append({"url": url, "params": params})
        return FakeResponse(data)

    return fake_get


def test_fetch_song_meta_parses_and_upscales_artwork():
    data = {
        "resultCount": 1,
        "results": [
            {
                "artworkUrl100": "https://is1.mzstatic.com/image/a/100x100bb.jpg",
                "previewUrl": "https://audio.example/preview.m4a",
            }
        ],
    }
    calls = []
    result = itunes_client.fetch_song_meta("Radiohead", "Creep", get_fn=make_get(data, calls))
    assert result == {
        "image_url": "https://is1.mzstatic.com/image/a/600x600bb.jpg",
        "preview_url": "https://audio.example/preview.m4a",
    }
    params = calls[0]["params"]
    assert params["term"] == "Radiohead Creep"
    assert params["media"] == "music"
    assert params["entity"] == "song"


def test_fetch_song_meta_returns_none_when_no_results():
    assert (
        itunes_client.fetch_song_meta(
            "x", "y", get_fn=make_get({"resultCount": 0, "results": []})
        )
        is None
    )
    assert itunes_client.fetch_song_meta("x", "y", get_fn=make_get({})) is None


def test_fetch_song_meta_keeps_artwork_when_no_size_token():
    data = {
        "resultCount": 1,
        "results": [{"artworkUrl100": "https://img/cover.jpg", "previewUrl": "https://a/p.m4a"}],
    }
    result = itunes_client.fetch_song_meta("a", "b", get_fn=make_get(data))
    assert result["image_url"] == "https://img/cover.jpg"


def test_fetch_artist_album_art_returns_upscaled_url():
    def fake_get(url, params=None, timeout=None):
        assert params["entity"] == "album"
        return FakeResponse({"results": [{"artworkUrl100": "http://a/100x100bb.jpg"}]})

    url = itunes_client.fetch_artist_album_art("potsu", get_fn=fake_get)
    assert url == "http://a/600x600bb.jpg"


def test_fetch_artist_album_art_returns_none_when_no_results():
    def fake_get(url, params=None, timeout=None):
        return FakeResponse({"results": []})

    assert itunes_client.fetch_artist_album_art("nobody", get_fn=fake_get) is None


def test_fetch_artist_album_art_returns_none_when_no_artwork():
    def fake_get(url, params=None, timeout=None):
        return FakeResponse({"results": [{"collectionName": "Album"}]})

    assert itunes_client.fetch_artist_album_art("x", get_fn=fake_get) is None
