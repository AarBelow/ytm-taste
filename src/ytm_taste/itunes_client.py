# src/ytm_taste/itunes_client.py
import requests

API_URL = "https://itunes.apple.com/search"


def fetch_song_meta(artist, track, get_fn=requests.get) -> dict | None:
    response = get_fn(
        API_URL,
        params={"term": f"{artist} {track}", "media": "music", "entity": "song", "limit": 1},
        timeout=10,
    )
    data = response.json()
    if not isinstance(data, dict):
        return None
    results = data.get("results") or []
    if not results:
        return None
    first = results[0]
    artwork = first.get("artworkUrl100")
    preview = first.get("previewUrl")
    if not artwork and not preview:
        return None
    image_url = artwork.replace("100x100bb", "600x600bb") if artwork else None
    return {"image_url": image_url, "preview_url": preview}


def fetch_artist_album_art(artist, get_fn=requests.get) -> str | None:
    response = get_fn(
        API_URL,
        params={"term": artist, "media": "music", "entity": "album", "limit": 1},
        timeout=10,
    )
    data = response.json()
    if not isinstance(data, dict):
        return None
    results = data.get("results") or []
    if not results:
        return None
    artwork = results[0].get("artworkUrl100")
    if not artwork:
        return None
    return artwork.replace("100x100bb", "600x600bb")
