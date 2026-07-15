# src/ytm_taste/song_resolver.py
import re

DASHES = ("-", "–", "—")
COVER_WORDS = ("cover", "remix", "bootleg", "mashup", "flip")

_BRACKETS = re.compile(r"[\(\[【][^\)\]】]*[\)\]】]")
_HASHTAG = re.compile(r"#\S+")


def clean_title(title: str) -> str:
    text = _BRACKETS.sub(" ", title or "")
    text = _HASHTAG.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -–—|·:")


def is_cover(title: str) -> bool:
    low = (title or "").lower()
    return any(word in low for word in COVER_WORDS)


def _split_on_dash(text: str):
    # Require spaces around the dash so hyphenated names ("lo-fi", "saib.-x") survive.
    for dash in DASHES:
        sep = f" {dash} "
        if sep in text:
            left, right = text.split(sep, 1)
            return left.strip(), right.strip()
    return None


def candidates(channel_title, title) -> list[tuple[str, str]]:
    cleaned = clean_title(title)
    guesses = []
    parts = _split_on_dash(cleaned)
    if parts:
        left, right = parts
        guesses.append((left, right))
        guesses.append((right, left))
    if channel_title:
        guesses.append((channel_title.strip(), cleaned))

    out: list[tuple[str, str]] = []
    seen = set()
    for artist, track in guesses:
        if not artist or not track:
            continue
        key = (artist.lower(), track.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((artist, track))
    return out


def resolve(channel_title, title, verify_fn) -> dict | None:
    for artist, track in candidates(channel_title, title):
        found = verify_fn(artist, track)
        if found:
            return {
                "artist": found["artist"],
                "track": found["track"],
                "is_cover": is_cover(title),
            }
    return None
