# src/ytm_taste/itunes_client.py
import requests

API_URL = "https://itunes.apple.com/search"

# iTunes drops marginal matches when asked for a short list: the identical search for
# "idealism Controlla" returns 0 results at limit=1 but 1 result at limit=3. Ask for a
# few and use the first; a bad question and a genuinely absent song both return nothing,
# so this failed silently.
SEARCH_LIMIT = 3


def _read_json(response):
    """iTunes rate-limits datacenter IPs (e.g. a hosted server) with an empty body,
    so response.json() raises. A blank response means 'no match', not a crash, so
    fall back to None and let the existing isinstance checks handle it."""
    try:
        return response.json()
    except ValueError:  # JSONDecodeError is a ValueError; also covers a non-JSON body
        return None


def fetch_song_meta(artist, track, get_fn=requests.get) -> dict | None:
    response = get_fn(
        API_URL,
        params={
            "term": f"{artist} {track}",
            "media": "music",
            "entity": "song",
            "limit": SEARCH_LIMIT,
        },
        timeout=10,
    )
    data = _read_json(response)
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
        params={"term": artist, "media": "music", "entity": "album", "limit": SEARCH_LIMIT},
        timeout=10,
    )
    data = _read_json(response)
    if not isinstance(data, dict):
        return None
    results = data.get("results") or []
    if not results:
        return None
    artwork = results[0].get("artworkUrl100")
    if not artwork:
        return None
    return artwork.replace("100x100bb", "600x600bb")
