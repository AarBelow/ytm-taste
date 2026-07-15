# src/ytm_taste/recommendations.py
from collections import defaultdict

MAX_SEED_SONGS = 100
MAX_RECOMMENDATIONS = 25

# The top 5 artists split TOP_BUDGET of the seeds by these shares; artists 6-10
# share the rest. Without a quota, plain rank-ordering lets the top-ranked artist's
# songs fill every slot before the second artist is reached -- measured on the real
# library: 50 seeds drawn from just 2 artists out of a 562-song pool.
TOP_SHARES = (0.35, 0.25, 0.20, 0.10, 0.10)
TOP_BUDGET = 0.8
TAIL_ARTISTS = 5


def _key(artist, track):
    return (artist.casefold(), track.casefold())


def _quotas(top_artists, limit) -> dict[str, int]:
    """Seed slots per artist, keyed case-insensitively, in rank order."""
    quotas: dict[str, int] = {}
    top_budget = int(limit * TOP_BUDGET)
    for i, (artist, _count) in enumerate(top_artists[: len(TOP_SHARES)]):
        quotas[artist.casefold()] = round(top_budget * TOP_SHARES[i])
    tail = top_artists[len(TOP_SHARES) : len(TOP_SHARES) + TAIL_ARTISTS]
    if tail:
        share = (limit - sum(quotas.values())) // len(tail)
        for artist, _count in tail:
            quotas[artist.casefold()] = share
    return quotas


def select_seeds(clean_songs, top_artists, limit=MAX_SEED_SONGS):
    # Artists are grouped case-insensitively: get_top_artists shows the dominant
    # spelling ("Kaz Moon") while resolved songs carry Last.fm's ("kaz moon"), and
    # an exact-string lookup would treat the latter as belonging to nobody.
    by_artist: dict[str, list] = {}
    for artist, track in clean_songs:
        by_artist.setdefault(artist.casefold(), []).append((artist, track))

    chosen: list[tuple[str, str]] = []
    used: set[tuple[str, str]] = set()

    def take(songs, room):
        for artist, track in songs:
            if room <= 0 or len(chosen) >= limit:
                return
            key = _key(artist, track)
            if key in used:
                continue  # a song both liked and in a playlist must not take two slots
            used.add(key)
            chosen.append((artist, track))
            room -= 1

    for artist_key, quota in _quotas(top_artists, limit).items():
        take(by_artist.get(artist_key, []), quota)

    # Spare slots -- an artist with fewer songs than its share -- flow down the
    # ranking rather than being wasted, then to anyone else left in the pool.
    if len(chosen) < limit:
        for artist, _count in top_artists:
            take(by_artist.get(artist.casefold(), []), limit)
            if len(chosen) >= limit:
                break
    if len(chosen) < limit:
        take(clean_songs, limit)
    return chosen[:limit]


def rank(similar_by_seed, owned_keys, limit=MAX_RECOMMENDATIONS):
    scores = defaultdict(float)
    display = {}
    for similar in similar_by_seed:
        for entry in similar:
            artist = entry["artist"]
            track = entry["track"]
            key = (artist.lower().strip(), track.lower().strip())
            if key in owned_keys:
                continue
            scores[key] += entry["match"]
            display.setdefault(key, (artist, track))
    ranked = sorted(
        scores.items(),
        key=lambda kv: (-kv[1], display[kv[0]][0], display[kv[0]][1]),
    )
    return [(display[key][0], display[key][1], score) for key, score in ranked[:limit]]
