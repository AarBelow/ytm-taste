# tests/test_lastfm_client.py
from ytm_taste import lastfm_client


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def make_get(data, calls):
    def fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": params})
        return FakeResponse(data)

    return fake_get


def test_fetch_similar_tracks_parses_payload_and_sends_params():
    data = {
        "similartracks": {
            "track": [
                {"name": "Song A", "match": "1.0", "artist": {"name": "Artist A"}},
                {"name": "Song B", "match": "0.5", "artist": {"name": "Artist B"}},
            ]
        }
    }
    calls = []
    result = lastfm_client.fetch_similar_tracks(
        "KEY", "Seed Artist", "Seed Track", get_fn=make_get(data, calls)
    )
    assert result == [
        {"artist": "Artist A", "track": "Song A", "match": 1.0},
        {"artist": "Artist B", "track": "Song B", "match": 0.5},
    ]
    params = calls[0]["params"]
    assert params["method"] == "track.getSimilar"
    assert params["artist"] == "Seed Artist"
    assert params["track"] == "Seed Track"
    assert params["api_key"] == "KEY"
    assert params["format"] == "json"


def test_fetch_similar_tracks_handles_single_track_dict():
    # Last.fm returns a bare dict (not a list) when there is exactly one result
    data = {
        "similartracks": {
            "track": {"name": "Only", "match": "0.9", "artist": {"name": "Solo"}}
        }
    }
    result = lastfm_client.fetch_similar_tracks(
        "KEY", "A", "B", get_fn=make_get(data, [])
    )
    assert result == [{"artist": "Solo", "track": "Only", "match": 0.9}]


def test_fetch_similar_tracks_empty_or_malformed_returns_empty_list():
    assert lastfm_client.fetch_similar_tracks("K", "A", "B", get_fn=make_get({}, [])) == []
    assert (
        lastfm_client.fetch_similar_tracks(
            "K", "A", "B", get_fn=make_get({"similartracks": {}}, [])
        )
        == []
    )
    assert (
        lastfm_client.fetch_similar_tracks(
            "K", "A", "B", get_fn=make_get({"error": 6, "message": "nope"}, [])
        )
        == []
    )


def test_fetch_artist_info_skips_junk_tags_and_returns_full_bio():
    data = {
        "artist": {
            "stats": {"listeners": "741785"},
            "bio": {
                "content": "Potsu is a Lo-Fi producer. A longer full bio. "
                '<a href="x">Read more on Last.fm</a>'
            },
            # "text" is junk, "canadian" is geographic; "Lo-Fi" is the first real genre
            "tags": {"tag": [{"name": "text"}, {"name": "canadian"}, {"name": "Lo-Fi"}]},
        }
    }
    result = lastfm_client.fetch_artist_info("KEY", "potsu", get_fn=make_get(data, []))
    assert result["genre"] == "Lo-Fi"
    assert result["listeners"] == 741785
    assert "Read more on Last.fm" not in result["bio"]
    assert "<a" not in result["bio"]
    # full bio, not truncated mid-sentence
    assert result["bio"] == "Potsu is a Lo-Fi producer. A longer full bio."


def test_fetch_artist_info_joins_up_to_two_genres():
    data = {
        "artist": {
            "stats": {"listeners": "1"},
            "bio": {"content": "x"},
            # "japanese" is geographic junk; "nu jazz" and "lo-fi" are both real genres
            "tags": {"tag": [{"name": "nu jazz"}, {"name": "japanese"}, {"name": "lo-fi"}]},
        }
    }
    result = lastfm_client.fetch_artist_info("K", "potsu", get_fn=make_get(data, []))
    assert result["genre"] == "nu jazz / lo-fi"


def test_fetch_artist_info_single_genre_when_only_one_matches():
    data = {
        "artist": {
            "stats": {"listeners": "1"},
            "bio": {"content": "x"},
            "tags": {"tag": [{"name": "text"}, {"name": "canadian"}, {"name": "Lo-Fi"}]},
        }
    }
    result = lastfm_client.fetch_artist_info("K", "x", get_fn=make_get(data, []))
    assert result["genre"] == "Lo-Fi"


def test_fetch_artist_info_genre_none_when_no_genre_tag():
    data = {
        "artist": {
            "stats": {"listeners": "1"},
            "bio": {"content": "x"},
            "tags": {"tag": [{"name": "text"}, {"name": "seen live"}]},
        }
    }
    assert lastfm_client.fetch_artist_info("K", "x", get_fn=make_get(data, []))["genre"] is None


def test_fetch_artist_info_none_when_missing():
    assert lastfm_client.fetch_artist_info("K", "x", get_fn=make_get({}, [])) is None
    assert (
        lastfm_client.fetch_artist_info(
            "K", "x", get_fn=make_get({"error": 6, "message": "not found"}, [])
        )
        is None
    )
