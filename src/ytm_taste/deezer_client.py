# src/ytm_taste/deezer_client.py
import requests

# Deezer's public search needs no key and, unlike iTunes, serves datacenter IPs
# without aggressive rate limiting -- which is why hosted syncs get covers and
# previews from here instead. Each hit carries an album cover and a 30s preview MP3,
# the same two things iTunes gave us, so this is a drop-in for the sync pipeline.
API_URL = "https://api.deezer.com/search"


def _read_json(response):
    """A blank or non-JSON body (rate limit, gateway error) makes response.json()
    raise; treat it as 'no results' so one bad reply can't crash the caller."""
    try:
        return response.json()
    except ValueError:  # JSONDecodeError is a ValueError; also covers a non-JSON body
        return None


def _search(term, get_fn) -> list:
    response = get_fn(API_URL, params={"q": term}, timeout=10)
    data = _read_json(response)
    if not isinstance(data, dict):
        return []
    return data.get("data") or []


def _cover(album: dict) -> str | None:
    # cover_big is 500x500 -- large enough for a card, smaller to download than the
    # 1000px cover_xl. Fall through the sizes so a partial album record still yields art.
    return album.get("cover_big") or album.get("cover_xl") or album.get("cover_medium") or None


def _top_track(artist, track, get_fn) -> dict | None:
    # Field-scoped search first so the top hit is the right recording; fall back to a
    # plain query, which recovers matches the scoped form misses on punctuation.
    results = _search(f'artist:"{artist}" track:"{track}"', get_fn)
    if not results:
        results = _search(f"{artist} {track}", get_fn)
    return results[0] if results else None


def fetch_song_meta(artist, track, get_fn=requests.get) -> dict | None:
    first = _top_track(artist, track, get_fn)
    if first is None:
        return None
    image_url = _cover(first.get("album") or {})
    preview = first.get("preview") or None  # Deezer sends "" when there's no preview
    if not image_url and not preview:
        return None
    return {"image_url": image_url, "preview_url": preview}


def fetch_preview_url(artist, track, get_fn=requests.get) -> str | None:
    """Look up a preview MP3 fresh at play time. Deezer signs preview URLs with a
    ~12-minute expiry, so unlike the cover they cannot be stored at sync time -- a
    stored one is dead before the page is ever opened."""
    first = _top_track(artist, track, get_fn)
    if first is None:
        return None
    return first.get("preview") or None


def fetch_artist_album_art(artist, get_fn=requests.get) -> str | None:
    results = _search(f'artist:"{artist}"', get_fn)
    if not results:
        results = _search(artist, get_fn)
    if not results:
        return None
    return _cover(results[0].get("album") or {})
