# src/ytm_taste/youtube_client.py
from googleapiclient.discovery import build

MUSIC_CATEGORY_ID = "10"


def build_youtube_client(credentials):
    return build("youtube", "v3", credentials=credentials)


def get_channel_id(youtube) -> str | None:
    response = youtube.channels().list(part="id", mine=True).execute()
    items = response.get("items", [])
    if not items:
        return None
    return items[0]["id"]


def fetch_liked_videos(youtube) -> list[dict]:
    videos = []
    page_token = None
    while True:
        response = (
            youtube.videos()
            .list(part="snippet", myRating="like", maxResults=50, pageToken=page_token)
            .execute()
        )
        for item in response.get("items", []):
            snippet = item["snippet"]
            if snippet.get("categoryId") != MUSIC_CATEGORY_ID:
                continue
            videos.append(
                {
                    "video_id": item["id"],
                    "title": snippet["title"],
                    "channel_title": snippet["channelTitle"],
                }
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return videos


def fetch_playlists(youtube) -> list[dict]:
    playlists = []
    page_token = None
    while True:
        response = (
            youtube.playlists()
            .list(part="snippet", mine=True, maxResults=50, pageToken=page_token)
            .execute()
        )
        for item in response.get("items", []):
            playlists.append({"playlist_id": item["id"], "title": item["snippet"]["title"]})
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return playlists


def fetch_playlist_items(youtube, playlist_id: str) -> list[dict]:
    items = []
    page_token = None
    while True:
        response = (
            youtube.playlistItems()
            .list(part="snippet", playlistId=playlist_id, maxResults=50, pageToken=page_token)
            .execute()
        )
        for item in response.get("items", []):
            snippet = item["snippet"]
            video_id = snippet.get("resourceId", {}).get("videoId")
            if not video_id:
                continue
            items.append({"video_id": video_id, "title": snippet["title"]})
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return items


def fetch_subscriptions(youtube) -> list[dict]:
    subscriptions = []
    page_token = None
    while True:
        response = (
            youtube.subscriptions()
            .list(part="snippet", mine=True, maxResults=50, pageToken=page_token)
            .execute()
        )
        for item in response.get("items", []):
            snippet = item["snippet"]
            subscriptions.append(
                {
                    "channel_id": snippet["resourceId"]["channelId"],
                    "channel_title": snippet["title"],
                }
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return subscriptions
