# tests/test_recommendations.py
from ytm_taste import recommendations


def test_select_seeds_orders_by_artist_rank_and_caps():
    clean = [
        ("Gamma", "g1"),  # Gamma is rank 2
        ("Alpha", "a1"),  # Alpha is rank 0
        ("Alpha", "a2"),
        ("Zeta", "z1"),  # unranked -> last
    ]
    top = [("Alpha", 10), ("Beta", 5), ("Gamma", 3)]
    seeds = recommendations.select_seeds(clean, top, limit=3)
    # Alpha songs first (rank 0), then Gamma (rank 2), Zeta dropped by cap
    assert seeds == [("Alpha", "a1"), ("Alpha", "a2"), ("Gamma", "g1")]


def test_select_seeds_unranked_artists_go_last():
    clean = [("Unknown", "u1"), ("Alpha", "a1")]
    top = [("Alpha", 10)]
    assert recommendations.select_seeds(clean, top, limit=5) == [
        ("Alpha", "a1"),
        ("Unknown", "u1"),
    ]


def test_rank_sums_match_scores_and_excludes_owned():
    similar_by_seed = [
        [
            {"artist": "New Band", "track": "Hit", "match": 0.5},
            {"artist": "Owned Band", "track": "Have It", "match": 0.9},
        ],
        [
            {"artist": "New Band", "track": "Hit", "match": 0.4},  # same track again
            {"artist": "Other", "track": "Tune", "match": 0.3},
        ],
    ]
    owned = {("owned band", "have it")}
    result = recommendations.rank(similar_by_seed, owned, limit=10)
    # New Band/Hit = 0.5 + 0.4 = 0.9 (top); Other/Tune = 0.3; Owned excluded
    assert result[0] == ("New Band", "Hit", 0.9)
    assert ("Other", "Tune", 0.3) in result
    assert all(artist != "Owned Band" for artist, _track, _score in result)


def test_rank_caps_at_limit():
    similar_by_seed = [
        [{"artist": f"A{i}", "track": f"T{i}", "match": float(i)} for i in range(10)]
    ]
    result = recommendations.rank(similar_by_seed, set(), limit=3)
    assert len(result) == 3
    # highest match first
    assert result[0] == ("A9", "T9", 9.0)
