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


def test_resolve_returns_the_verified_candidate_with_canonical_names():
    def verify(artist, track):
        # only the reversed split is real: "Eve x suis" / "平行線"
        if artist == "Eve x suis" and track == "平行線":
            return {"artist": "Eve", "track": "平行線", "listeners": 52}
        return None

    got = song_resolver.resolve("Eve", "平行線 - Eve x suis", verify)
    assert got == {"artist": "Eve", "track": "平行線", "listeners": 52, "is_cover": False}


def test_resolve_picks_the_candidate_with_the_most_listeners_not_the_first():
    # Real case from the library: "Memories - Maroon 5 ( Gawr Gura cover)".
    # The forward split is a real Last.fm entry (185 scrobbled listeners) but it is
    # BACKWARDS. The reversed split is the true song (720k). First-hit-wins picked
    # the wrong one, so resolve must weigh candidates by listeners.
    def verify(artist, track):
        if (artist, track) == ("Memories", "Maroon 5"):
            return {"artist": "Memories", "track": "MAROON 5", "listeners": 185}
        if (artist, track) == ("Maroon 5", "Memories"):
            return {"artist": "Maroon 5", "track": "Memories", "listeners": 720496}
        return None

    got = song_resolver.resolve("BC", "Memories - Maroon 5 ( Gawr Gura cover)", verify)
    assert got["artist"] == "Maroon 5"
    assert got["track"] == "Memories"
    assert got["listeners"] == 720496
    assert got["is_cover"] is True


def test_resolve_evaluates_every_candidate():
    calls = []

    def verify(artist, track):
        calls.append((artist, track))
        return {"artist": artist, "track": track, "listeners": 1}

    song_resolver.resolve("Ch", "A - B", verify)
    assert len(calls) == 3  # forward split, reversed split, channel-as-artist


def test_resolve_returns_none_when_nothing_verifies():
    got = song_resolver.resolve("Arf Ch.", "It will be a journey #shorts", lambda a, t: None)
    assert got is None


def test_resolve_marks_covers_from_the_raw_title():
    got = song_resolver.resolve(
        "BC", "Memories - Maroon 5 ( Gawr Gura cover)",
        lambda a, t: (
            {"artist": "Maroon 5", "track": "Memories", "listeners": 9}
            if a == "Maroon 5"
            else None
        ),
    )
    assert got == {"artist": "Maroon 5", "track": "Memories", "listeners": 9, "is_cover": True}
