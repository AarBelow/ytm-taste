# src/ytm_taste/recommendations.py
from collections import defaultdict

MAX_SEED_SONGS = 50
MAX_RECOMMENDATIONS = 50


def select_seeds(clean_songs, top_artists, limit=MAX_SEED_SONGS):
    rank_of = {artist: i for i, (artist, _count) in enumerate(top_artists)}
    unranked = len(rank_of)
    ordered = sorted(
        enumerate(clean_songs),
        key=lambda item: (rank_of.get(item[1][0], unranked), item[0]),
    )
    return [song for _idx, song in ordered][:limit]


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
