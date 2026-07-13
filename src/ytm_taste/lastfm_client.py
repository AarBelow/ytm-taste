# src/ytm_taste/lastfm_client.py
import re

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


def _clean_bio(summary: str, limit: int = 220) -> str:
    text = re.sub(r"<[^>]+>", "", summary or "")
    text = text.replace("Read more on Last.fm", "").strip()
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0].rstrip(".,;: ")
        text = cut + "…"
    return text


def fetch_artist_info(api_key, artist, get_fn=requests.get) -> dict | None:
    response = get_fn(
        API_URL,
        params={
            "method": "artist.getInfo",
            "artist": artist,
            "api_key": api_key,
            "format": "json",
        },
        timeout=10,
    )
    data = response.json()
    if not isinstance(data, dict) or "artist" not in data:
        return None
    a = data["artist"]
    tags = a.get("tags", {}).get("tag", [])
    if isinstance(tags, dict):
        tags = [tags]
    genre = tags[0]["name"] if tags else None
    bio = _clean_bio(a.get("bio", {}).get("summary", "")) or None
    listeners_raw = a.get("stats", {}).get("listeners")
    try:
        listeners = int(listeners_raw) if listeners_raw is not None else None
    except (ValueError, TypeError):
        listeners = None
    return {"genre": genre, "bio": bio, "listeners": listeners}
