# src/ytm_taste/lastfm_client.py
import re

import requests

from ytm_taste.genres import GENRES

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


def _clean_bio(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return text.split("Read more on Last.fm")[0].strip()


def _pick_genre(tags) -> str | None:
    # Pick the first tag that is a real music genre, skipping junk/geographic tags.
    for t in tags:
        name = t.get("name") if isinstance(t, dict) else None
        if name and name.lower() in GENRES:
            return name
    return None


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
    genre = _pick_genre(tags)
    bio_raw = a.get("bio", {}).get("content") or a.get("bio", {}).get("summary", "")
    bio = _clean_bio(bio_raw) or None
    listeners_raw = a.get("stats", {}).get("listeners")
    try:
        listeners = int(listeners_raw) if listeners_raw is not None else None
    except (ValueError, TypeError):
        listeners = None
    return {"genre": genre, "bio": bio, "listeners": listeners}
