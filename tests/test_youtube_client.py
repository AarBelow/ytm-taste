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
                "snippet": {
                    "title": "Song One",
                    "channelTitle": "Artist One",
                    "channelId": "UC1",
                    "categoryId": "10",
                },
            },
            {
                "id": "v2",
                "snippet": {"title": "Some Vlog", "channelTitle": "Vlogger", "categoryId": "22"},
            },
        ]
    }
    youtube = FakeYoutube(videos=FakeResource({None: response}))
    result = youtube_client.fetch_liked_videos(youtube)
    assert result == [
        {"video_id": "v1", "title": "Song One", "channel_title": "Artist One", "channel_id": "UC1"}
    ]


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


class FakeVideosResource:
    """Fakes youtube.videos().list(id=...).execute(), returning canned items
    per comma-joined id string and recording each id argument."""

    def __init__(self, items_by_id):
        self._items_by_id = items_by_id
        self.id_args = []

    def videos(self):
        return self

    def list(self, **kwargs):
        self.id_args.append(kwargs["id"])
        requested = kwargs["id"].split(",")
        items = [self._items_by_id[i] for i in requested if i in self._items_by_id]
        return FakeRequest({"items": items})


def _video_item(video_id, channel_title, category_id):
    return {
        "id": video_id,
        "snippet": {
            "channelTitle": channel_title,
            "channelId": "UC" + video_id,
            "categoryId": category_id,
        },
    }


def test_fetch_video_details_returns_channel_and_category_map():
    youtube = FakeVideosResource(
        {
            "v1": _video_item("v1", "Artist One", "10"),
            "v2": _video_item("v2", "Some Vlogger", "22"),
        }
    )
    result = youtube_client.fetch_video_details(youtube, ["v1", "v2"])
    assert result == {
        "v1": {"channel_title": "Artist One", "category_id": "10", "channel_id": "UCv1"},
        "v2": {"channel_title": "Some Vlogger", "category_id": "22", "channel_id": "UCv2"},
    }


def test_fetch_video_details_empty_list_makes_no_api_call():
    youtube = FakeVideosResource({})
    result = youtube_client.fetch_video_details(youtube, [])
    assert result == {}
    assert youtube.id_args == []


def test_fetch_video_details_batches_in_groups_of_50():
    ids = [f"v{n}" for n in range(120)]
    items = {vid: _video_item(vid, f"ch{vid}", "10") for vid in ids}
    youtube = FakeVideosResource(items)
    result = youtube_client.fetch_video_details(youtube, ids)
    assert len(result) == 120
    # 120 ids -> 3 calls (50 + 50 + 20), order not guaranteed under concurrency
    assert len(youtube.id_args) == 3
    assert any(a.count(",") == 49 for a in youtube.id_args)  # the 50-id batch exists


def test_fetch_video_details_omits_ids_with_no_item():
    youtube = FakeVideosResource({"v1": _video_item("v1", "Artist One", "10")})
    result = youtube_client.fetch_video_details(youtube, ["v1", "missing"])
    assert result == {
        "v1": {"channel_title": "Artist One", "category_id": "10", "channel_id": "UCv1"}
    }


class FakeChannelsResource:
    def __init__(self, items_by_id):
        self._items = items_by_id
        self.id_args = []

    def channels(self):
        return self

    def list(self, **kwargs):
        self.id_args.append(kwargs["id"])
        ids = kwargs["id"].split(",")
        return FakeRequest({"items": [self._items[i] for i in ids if i in self._items]})


def test_fetch_channel_avatars_maps_id_to_thumbnail():
    items = {
        "UC1": {"id": "UC1", "snippet": {"thumbnails": {"default": {"url": "http://a/1.jpg"}}}},
    }
    youtube = FakeChannelsResource(items)
    assert youtube_client.fetch_channel_avatars(youtube, ["UC1"]) == {"UC1": "http://a/1.jpg"}


def test_fetch_channel_avatars_empty_list_no_call():
    youtube = FakeChannelsResource({})
    assert youtube_client.fetch_channel_avatars(youtube, []) == {}
    assert youtube.id_args == []
