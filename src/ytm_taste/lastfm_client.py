# src/ytm_taste/lastfm_client.py
import re

import requests

from ytm_taste.genres import GENRES

API_URL = "http://ws.audioscrobbler.com/2.0/"


def _read_json(response):
    """A blank or non-JSON body (rate limit, gateway error) makes response.json()
    raise; treat it as 'no data' so a single bad response can't crash the caller."""
    try:
        return response.json()
    except ValueError:  # JSONDecodeError is a ValueError; also covers a non-JSON body
        return None


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
    data = _read_json(response)
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


def _pick_genres(tags, limit=2) -> str | None:
    # Pick up to `limit` real music-genre tags (skipping junk/geographic ones),
    # preserving Last.fm's tag order, joined with " / " (e.g. "nu jazz / lo-fi").
    picked: list[str] = []
    seen: set[str] = set()
    for t in tags:
        name = t.get("name") if isinstance(t, dict) else None
        if not name:
            continue
        low = name.lower()
        if low in GENRES and low not in seen:
            picked.append(name)
            seen.add(low)
            if len(picked) >= limit:
                break
    return " / ".join(picked) if picked else None


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
    data = _read_json(response)
    if not isinstance(data, dict) or "artist" not in data:
        return None
    a = data["artist"]
    tags = a.get("tags", {}).get("tag", [])
    if isinstance(tags, dict):
        tags = [tags]
    genre = _pick_genres(tags)
    bio_raw = a.get("bio", {}).get("content") or a.get("bio", {}).get("summary", "")
    bio = _clean_bio(bio_raw) or None
    listeners_raw = a.get("stats", {}).get("listeners")
    try:
        listeners = int(listeners_raw) if listeners_raw is not None else None
    except (ValueError, TypeError):
        listeners = None
    return {"genre": genre, "bio": bio, "listeners": listeners}


def verify_track(api_key, artist, track, get_fn=requests.get) -> dict | None:
    response = get_fn(
        API_URL,
        params={
            "method": "track.getInfo",
            "artist": artist,
            "track": track,
            "api_key": api_key,
            "autocorrect": 1,
            "format": "json",
        },
        timeout=10,
    )
    data = _read_json(response)
    if not isinstance(data, dict):
        return None
    found = data.get("track")
    if not isinstance(found, dict):
        return None
    name = found.get("name")
    artist_name = (found.get("artist") or {}).get("name")
    if not name or not artist_name:
        return None
    # Last.fm's catalogue is built from scrobbles, so almost any string "exists".
    # Listener count is what separates a real song from a stray scrobble.
    try:
        listeners = int(found.get("listeners") or 0)
    except (TypeError, ValueError):
        listeners = 0
    return {"artist": artist_name, "track": name, "listeners": listeners}
