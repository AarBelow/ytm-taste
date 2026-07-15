# tests/test_recommendations.py
from collections import Counter

from ytm_taste import recommendations


def _pool(spec):
    songs = []
    for artist, n in spec.items():
        songs += [(artist, f"{artist} track {i}") for i in range(n)]
    return songs


def _tops(spec):
    return [(a, n) for a, n in spec.items()]


def test_select_seeds_allocates_the_top5_shares_and_tail():
    spec = {
        "A": 40, "B": 40, "C": 40, "D": 40, "E": 40,  # top 5
        "F": 20, "G": 20, "H": 20, "I": 20, "J": 20,  # 6-10
        "K": 20,                                       # 11th gets nothing
    }
    got = recommendations.select_seeds(_pool(spec), _tops(spec), limit=100)
    counts = Counter(a for a, _t in got)
    assert counts["A"] == 28  # 35% of the 80-slot top-5 budget
    assert counts["B"] == 20  # 25%
    assert counts["C"] == 16  # 20%
    assert counts["D"] == 8   # 10%
    assert counts["E"] == 8   # 10%
    assert counts["F"] == counts["G"] == counts["H"] == counts["I"] == counts["J"] == 4
    assert "K" not in counts
    assert len(got) == 100


def test_select_seeds_reaches_ten_artists_instead_of_two():
    # The measured bug: rank-ordering let the top 2 artists eat all 50 slots.
    spec = {"A": 300, "B": 200, "C": 100, "D": 50, "E": 50,
            "F": 20, "G": 20, "H": 20, "I": 20, "J": 20}
    got = recommendations.select_seeds(_pool(spec), _tops(spec), limit=100)
    assert len({a for a, _t in got}) == 10


def test_select_seeds_flows_unfilled_quota_down_instead_of_wasting_it():
    # D's share is 8 but it only has 2 songs -> the spare slots must be reused.
    spec = {"A": 40, "B": 40, "C": 40, "D": 2, "E": 40, "F": 20}
    got = recommendations.select_seeds(_pool(spec), _tops(spec), limit=100)
    counts = Counter(a for a, _t in got)
    assert counts["D"] == 2
    assert len(got) == 100  # no wasted slots


def test_select_seeds_groups_case_variants_together():
    # get_top_artists displays "Kaz Moon"; resolved songs carry Last.fm's "kaz moon".
    songs = [("Kaz Moon", "topic song"), ("kaz moon", "resolved song")]
    got = recommendations.select_seeds(songs, [("Kaz Moon", 30)], limit=10)
    assert ("kaz moon", "resolved song") in got  # not treated as a stranger and dropped


def test_select_seeds_does_not_let_a_duplicate_take_two_slots():
    songs = [("A", "same"), ("A", "same"), ("A", "other")]
    got = recommendations.select_seeds(songs, [("A", 3)], limit=10)
    assert got.count(("A", "same")) == 1


def test_select_seeds_handles_a_tiny_pool():
    assert recommendations.select_seeds([("A", "x")], [("A", 1)], limit=100) == [("A", "x")]


def test_select_seeds_respects_the_limit():
    got = recommendations.select_seeds(_pool({"A": 500}), _tops({"A": 500}), limit=100)
    assert len(got) == 100


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


def test_rank_defaults_reproduce_todays_behaviour():
    similar = [
        [{"artist": "A", "track": "x", "match": 0.5}],
        [{"artist": "A", "track": "x", "match": 0.5}],
        [{"artist": "B", "track": "y", "match": 0.9}],
    ]
    got = recommendations.rank(similar, owned_keys=set())
    assert got[0] == ("A", "x", 1.0)  # summed, breadth beats depth
    assert got[1] == ("B", "y", 0.9)


def test_rank_adventurous_mode_uses_the_strongest_single_match_not_the_sum():
    # The J Dilla case: one seed adores B (0.9); three seeds shrug at A (0.5 each).
    similar = [
        [{"artist": "A", "track": "x", "match": 0.5}],
        [{"artist": "A", "track": "x", "match": 0.5}],
        [{"artist": "A", "track": "x", "match": 0.5}],
        [{"artist": "B", "track": "y", "match": 0.9}],
    ]
    safe = recommendations.rank(similar, owned_keys=set(), mode="safe")
    assert safe[0][0] == "A"  # 1.5 summed beats 0.9
    bold = recommendations.rank(similar, owned_keys=set(), mode="adventurous")
    assert bold[0] == ("B", "y", 0.9)  # strongest single match wins
    assert bold[1] == ("A", "x", 0.5)


def test_rank_discovery_new_demotes_artists_you_already_have():
    similar = [
        [{"artist": "Known", "track": "x", "match": 1.0}],
        [{"artist": "Known", "track": "x", "match": 1.0}],
        [{"artist": "Fresh", "track": "y", "match": 0.5}],
    ]
    known = {"known"}
    love = recommendations.rank(similar, set(), known_artists=known, discovery="love")
    assert love[0][0] == "Known"  # 2.0 vs 0.5 -- unchanged from today
    new = recommendations.rank(similar, set(), known_artists=known, discovery="new")
    assert new[0][0] == "Fresh"  # 2.0 * 0.1 = 0.2, beaten by 0.5
    assert new[1][0] == "Known"  # still present, just demoted


def test_rank_discovery_matches_known_artists_case_insensitively():
    similar = [[{"artist": "kaz moon", "track": "x", "match": 1.0}],
               [{"artist": "Fresh", "track": "y", "match": 0.5}]]
    got = recommendations.rank(similar, set(), known_artists={"Kaz Moon".casefold()},
                               discovery="new")
    assert got[0][0] == "Fresh"


def test_rank_keeps_fifty_recommendations_by_default():
    # 10 pages of 5, so Refresh shows new songs instead of looping after 5 clicks.
    # 50 is where this library's scores flatten out: rank 25 scores 1.04, rank 50
    # scores 0.98, and only 43 songs score >= 1.0 at all. Past ~50 every remaining
    # song is one seed weakly mentioning it once.
    similar = [
        [{"artist": f"A{i}", "track": f"T{i}", "match": 1.0 - i / 1000} for i in range(200)]
    ]
    assert len(recommendations.rank(similar, owned_keys=set())) == 50
    assert recommendations.MAX_RECOMMENDATIONS == 50


def test_rank_caps_at_limit():
    similar_by_seed = [
        [{"artist": f"A{i}", "track": f"T{i}", "match": float(i)} for i in range(10)]
    ]
    result = recommendations.rank(similar_by_seed, set(), limit=3)
    assert len(result) == 3
    # highest match first
    assert result[0] == ("A9", "T9", 9.0)


def test_max_recommendations_is_50():
    assert recommendations.MAX_RECOMMENDATIONS == 50
