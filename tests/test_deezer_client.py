# tests/test_deezer_client.py
import json

from ytm_taste import deezer_client


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class EmptyBodyResponse:
    def json(self):
        return json.loads("")  # JSONDecodeError, as a rate-limited/blank body would


def make_get(data, calls=None):
    def fake_get(url, params=None, timeout=None):
        if calls is not None:
            calls.append({"url": url, "params": params})
        return FakeResponse(data)

    return fake_get


def _song(preview="https://cdn/preview.mp3", cover_big="https://img/cover_big.jpg",
          artist="A", **album):
    album = {"cover_big": cover_big, **album}
    return {"title": "T", "artist": {"name": artist}, "preview": preview, "album": album}


def test_fetch_song_meta_returns_cover_and_preview():
    calls = []
    result = deezer_client.fetch_song_meta("potsu", "friends", get_fn=make_get(
        {"data": [_song()]}, calls))
    assert result == {
        "image_url": "https://img/cover_big.jpg",
        "preview_url": "https://cdn/preview.mp3",
    }
    # precise field-scoped query, so the top hit is the right track
    assert 'artist:"potsu"' in calls[0]["params"]["q"]
    assert 'track:"friends"' in calls[0]["params"]["q"]


def test_fetch_song_meta_falls_back_to_a_plain_query_when_scoped_search_is_empty():
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params["q"])
        # first (scoped) call finds nothing; second (plain) call finds the track
        data = {"data": []} if len(calls) == 1 else {"data": [_song()]}
        return FakeResponse(data)

    result = deezer_client.fetch_song_meta("potsu", "friends", get_fn=fake_get)
    assert result is not None
    assert len(calls) == 2
    assert 'artist:"' not in calls[1]  # the fallback is an unscoped query


def test_fetch_song_meta_returns_none_when_nothing_matches():
    assert deezer_client.fetch_song_meta("x", "y", get_fn=make_get({"data": []})) is None


def test_fetch_song_meta_treats_blank_preview_as_absent():
    # Deezer returns "" for tracks with no preview; that must become None, not "".
    result = deezer_client.fetch_song_meta("a", "b", get_fn=make_get({"data": [_song(preview="")]}))
    assert result["preview_url"] is None
    assert result["image_url"] == "https://img/cover_big.jpg"


def test_fetch_song_meta_returns_none_on_empty_body():
    def fake_get(url, params=None, timeout=None):
        return EmptyBodyResponse()

    assert deezer_client.fetch_song_meta("a", "b", get_fn=fake_get) is None


def test_fetch_artist_album_art_returns_a_cover_url():
    data = {"data": [_song(artist="King Gnu")]}
    result = deezer_client.fetch_artist_album_art("King Gnu", get_fn=make_get(data))
    assert result == "https://img/cover_big.jpg"


def test_fetch_artist_album_art_skips_results_by_a_different_artist():
    # The real Kaz Moon bug: Deezer's fuzzy artist filter ranked a stranger's track
    # first. We must take the first result actually BY the searched artist.
    data = {
        "data": [
            _song(artist="KARD", cover_big="https://img/WRONG.jpg"),
            _song(artist="Kaz Moon", cover_big="https://img/right.jpg"),
        ]
    }
    result = deezer_client.fetch_artist_album_art("Kaz Moon", get_fn=make_get(data))
    assert result == "https://img/right.jpg"


def test_fetch_artist_album_art_matches_artist_case_insensitively():
    data = {"data": [_song(artist="kaz moon", cover_big="https://img/c.jpg")]}
    assert deezer_client.fetch_artist_album_art("Kaz Moon", get_fn=make_get(data)) == "https://img/c.jpg"


def test_fetch_artist_album_art_returns_none_when_no_result_is_by_the_artist():
    # Only a stranger's track came back -> better no background than a wrong one.
    data = {"data": [_song(artist="Somebody Else")]}
    assert deezer_client.fetch_artist_album_art("Kaz Moon", get_fn=make_get(data)) is None


def test_fetch_artist_album_art_returns_none_when_empty():
    assert deezer_client.fetch_artist_album_art("nobody", get_fn=make_get({"data": []})) is None


def test_fetch_artist_album_art_returns_none_on_empty_body():
    def fake_get(url, params=None, timeout=None):
        return EmptyBodyResponse()

    assert deezer_client.fetch_artist_album_art("a", get_fn=fake_get) is None
