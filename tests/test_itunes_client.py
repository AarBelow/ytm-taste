# tests/test_itunes_client.py
import json

from ytm_taste import itunes_client


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class EmptyBodyResponse:
    """iTunes rate-limits datacenter IPs (e.g. Railway) with an empty 403 body, so
    response.json() raises JSONDecodeError instead of returning data."""

    def json(self):
        return json.loads("")  # raises "Expecting value: line 1 column 1 (char 0)"


def make_empty_get():
    def fake_get(url, params=None, timeout=None):
        return EmptyBodyResponse()

    return fake_get


def test_fetch_artist_album_art_returns_none_on_empty_body_instead_of_crashing():
    # Observed on Railway: an empty iTunes response crashed the whole sync's artist
    # enrichment, which rolled back the avatars and genres fetched alongside it.
    assert itunes_client.fetch_artist_album_art("potsu", get_fn=make_empty_get()) is None


def test_fetch_song_meta_returns_none_on_empty_body_instead_of_crashing():
    assert itunes_client.fetch_song_meta("a", "b", get_fn=make_empty_get()) is None


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


def test_song_meta_asks_for_more_than_one_result_but_uses_the_first():
    # Measured against the live API: the identical search returns 0 results at
    # limit=1 but 1 result at limit=3 -- asking for a shorter list makes marginal
    # matches vanish. Costing us real songs (idealism - Controlla).
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params)
        return FakeResponse(
            {
                "results": [
                    {"artworkUrl100": "http://first/100x100bb.jpg", "previewUrl": "http://p1"},
                    {"artworkUrl100": "http://second/100x100bb.jpg", "previewUrl": "http://p2"},
                ]
            }
        )

    got = itunes_client.fetch_song_meta("A", "T", get_fn=fake_get)
    assert captured["limit"] > 1
    assert got == {"image_url": "http://first/600x600bb.jpg", "preview_url": "http://p1"}


def test_artist_album_art_asks_for_more_than_one_result_but_uses_the_first():
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params)
        return FakeResponse(
            {
                "results": [
                    {"artworkUrl100": "http://first/100x100bb.jpg"},
                    {"artworkUrl100": "http://second/100x100bb.jpg"},
                ]
            }
        )

    got = itunes_client.fetch_artist_album_art("A", get_fn=fake_get)
    assert captured["limit"] > 1
    assert got == "http://first/600x600bb.jpg"
