# tests/test_youtube_client.py
from ytm_taste import youtube_client


class FakeRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class FakeResource:
    """Fakes the `.list(**kwargs).execute()` chain, keyed by pageToken."""

    def __init__(self, responses_by_page_token):
        self._responses = responses_by_page_token
        self.list_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        page_token = kwargs.get("pageToken")
        return FakeRequest(self._responses[page_token])


class FakeYoutube:
    def __init__(
        self, channels=None, videos=None, playlists=None, playlist_items=None, subscriptions=None
    ):
        self._channels = channels
        self._videos = videos
        self._playlists = playlists
        self._playlist_items = playlist_items
        self._subscriptions = subscriptions

    def channels(self):
        return self._channels

    def videos(self):
        return self._videos

    def playlists(self):
        return self._playlists

    def playlistItems(self):
        return self._playlist_items

    def subscriptions(self):
        return self._subscriptions


def test_get_channel_id_returns_id_when_present():
    youtube = FakeYoutube(channels=FakeResource({None: {"items": [{"id": "UC123"}]}}))
    assert youtube_client.get_channel_id(youtube) == "UC123"


def test_get_channel_id_returns_none_when_no_channel():
    youtube = FakeYoutube(channels=FakeResource({None: {"items": []}}))
    assert youtube_client.get_channel_id(youtube) is None


def test_fetch_liked_videos_filters_to_music_category_only():
    response = {
        "items": [
            {
                "id": "v1",
                "snippet": {"title": "Song One", "channelTitle": "Artist One", "categoryId": "10"},
            },
            {
                "id": "v2",
                "snippet": {"title": "Some Vlog", "channelTitle": "Vlogger", "categoryId": "22"},
            },
        ]
    }
    youtube = FakeYoutube(videos=FakeResource({None: response}))
    result = youtube_client.fetch_liked_videos(youtube)
    assert result == [{"video_id": "v1", "title": "Song One", "channel_title": "Artist One"}]


def test_fetch_liked_videos_paginates_across_multiple_pages():
    page1 = {
        "items": [
            {"id": "v1", "snippet": {"title": "Song One", "channelTitle": "A1", "categoryId": "10"}}
        ],
        "nextPageToken": "page2",
    }
    page2 = {
        "items": [
            {"id": "v2", "snippet": {"title": "Song Two", "channelTitle": "A2", "categoryId": "10"}}
        ]
    }
    youtube = FakeYoutube(videos=FakeResource({None: page1, "page2": page2}))
    result = youtube_client.fetch_liked_videos(youtube)
    assert [v["video_id"] for v in result] == ["v1", "v2"]


def test_fetch_playlists_returns_id_and_title():
    response = {"items": [{"id": "PL1", "snippet": {"title": "My Mix"}}]}
    youtube = FakeYoutube(playlists=FakeResource({None: response}))
    assert youtube_client.fetch_playlists(youtube) == [{"playlist_id": "PL1", "title": "My Mix"}]


def test_fetch_playlist_items_returns_video_id_and_title():
    response = {
        "items": [
            {"snippet": {"title": "Song One", "resourceId": {"videoId": "v1"}}},
        ]
    }
    youtube = FakeYoutube(playlist_items=FakeResource({None: response}))
    result = youtube_client.fetch_playlist_items(youtube, "PL1")
    assert result == [{"video_id": "v1", "title": "Song One"}]


def test_fetch_subscriptions_returns_channel_id_and_title():
    response = {
        "items": [{"snippet": {"title": "Some Artist", "resourceId": {"channelId": "UC999"}}}]
    }
    youtube = FakeYoutube(subscriptions=FakeResource({None: response}))
    result = youtube_client.fetch_subscriptions(youtube)
    assert result == [{"channel_id": "UC999", "channel_title": "Some Artist"}]
