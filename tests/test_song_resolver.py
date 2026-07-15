# tests/test_song_resolver.py
from ytm_taste import song_resolver


def test_clean_title_strips_bracket_junk_and_hashtags():
    assert song_resolver.clean_title("Giga - 'G4L'【MV】") == "Giga - 'G4L'"
    assert (
        song_resolver.clean_title("Trippie Redd - Death (Guitar Remix)")
        == "Trippie Redd - Death"
    )
    assert (
        song_resolver.clean_title("[Romaji Lyrics] Goodbye Sengen")
        == "Goodbye Sengen"
    )
    assert (
        song_resolver.clean_title(
            "It will be a journey #hololive #shorts"
        )
        == "It will be a journey"
    )
    assert (
        song_resolver.clean_title("saib. - in your arms.")
        == "saib. - in your arms."
    )


def test_is_cover_detects_covers_and_remixes():
    assert song_resolver.is_cover("Memories - Maroon 5 ( Gawr Gura cover)") is True
    assert song_resolver.is_cover("Trippie Redd - Death (Guitar Remix)") is True
    assert song_resolver.is_cover("saib. - in your arms.") is False


def test_candidates_yields_both_dash_orderings_then_channel_as_artist():
    got = song_resolver.candidates("1171dominoV2", "saib. - in your arms.")
    assert got[0] == ("saib.", "in your arms.")
    assert got[1] == ("in your arms.", "saib.")
    assert got[2] == ("1171dominoV2", "saib. - in your arms.")


def test_candidates_without_a_dash_only_uses_channel_as_artist():
    assert song_resolver.candidates("AZALI", "constricted") == [("AZALI", "constricted")]


def test_candidates_handles_en_dash():
    got = song_resolver.candidates("Ch", "Elgar – Serenade for Strings")
    assert got[0] == ("Elgar", "Serenade for Strings")


def test_candidates_are_deduped_and_drop_empty_parts():
    got = song_resolver.candidates("Eve", "Eve")
    assert got == [("Eve", "Eve")]


def test_resolve_returns_first_verified_candidate_with_canonical_names():
    calls = []

    def verify(artist, track):
        calls.append((artist, track))
        # only the reversed split is real: "Eve x suis" / "平行線"
        if artist == "Eve x suis" and track == "平行線":
            return {"artist": "Eve", "track": "平行線"}
        return None

    got = song_resolver.resolve("Eve", "平行線 - Eve x suis", verify)
    assert got == {"artist": "Eve", "track": "平行線", "is_cover": False}
    assert calls[0] == ("平行線", "Eve x suis")  # tried the forward split first


def test_resolve_stops_calling_verify_after_the_first_hit():
    calls = []

    def verify(artist, track):
        calls.append((artist, track))
        return {"artist": artist, "track": track}

    song_resolver.resolve("Ch", "A - B", verify)
    assert len(calls) == 1


def test_resolve_returns_none_when_nothing_verifies():
    got = song_resolver.resolve("Arf Ch.", "It will be a journey #shorts", lambda a, t: None)
    assert got is None


def test_resolve_marks_covers_from_the_raw_title():
    got = song_resolver.resolve(
        "BC", "Memories - Maroon 5 ( Gawr Gura cover)",
        lambda a, t: {"artist": "Maroon 5", "track": "Memories"} if a == "Maroon 5" else None,
    )
    assert got == {"artist": "Maroon 5", "track": "Memories", "is_cover": True}
