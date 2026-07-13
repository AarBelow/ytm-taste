# src/ytm_taste/lastfm_client.py
import requests

API_URL = "http://ws.audioscrobbler.com/2.0/"


def fetch_similar_tracks(api_key, artist, track, limit=50, get_fn=requests.get) -> list[dict]:
    response = get_fn(
        API_URL,
        params={
            "method": "track.getSimilar",
            "artist": artist,
            "track": track,
            "api_key": api_key,
            "autocorrect": 1,
            "limit": limit,
            "format": "json",
        },
        timeout=10,
    )
    data = response.json()
    if not isinstance(data, dict):
        return []
    tracks = data.get("similartracks", {}).get("track", [])
    if isinstance(tracks, dict):  # single-result payloads come back as a bare dict
        tracks = [tracks]
    result = []
    for t in tracks:
        try:
            result.append(
                {
                    "artist": t["artist"]["name"],
                    "track": t["name"],
                    "match": float(t["match"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return result
