# src/ytm_taste/genres.py
# A general vocabulary of music genres used to pick a real genre from Last.fm's
# community tags (which mix genres with junk like "text" and geographic tags
# like "Canadian"). This is a reusable classification list, NOT per-artist data.
# All entries are lowercase; tags are matched case-insensitively.

GENRES = frozenset(
    {
        # broad families
        "pop", "rock", "jazz", "blues", "folk", "country", "classical", "metal",
        "punk", "soul", "funk", "disco", "reggae", "ska", "gospel", "electronic",
        "hip hop", "hip-hop", "rap", "r&b", "rnb", "dance", "house", "techno",
        "trance", "dubstep", "drum and bass", "drum n bass", "ambient", "instrumental",
        "soundtrack", "orchestral", "opera", "world", "latin", "afrobeat", "k-pop",
        "j-pop", "j-rock", "city pop", "new age", "experimental", "industrial",
        "grunge", "emo", "hardcore", "post-rock", "post-punk", "shoegaze",
        # pop / rock subgenres
        "indie", "indie pop", "indie rock", "dream pop", "synthpop", "synth-pop",
        "electropop", "art pop", "power pop", "alternative", "alternative rock",
        "classic rock", "hard rock", "soft rock", "psychedelic rock", "progressive rock",
        "garage rock", "surf rock", "folk rock", "pop punk", "bedroom pop",
        "hyperpop", "chamber pop", "baroque pop",
        # electronic subgenres
        "edm", "idm", "downtempo", "trip hop", "trip-hop", "lo-fi", "lofi",
        "lo-fi hip hop", "lo-fi rap", "chillhop", "chillwave", "chill", "vaporwave",
        "future bass", "electro", "electronica", "breakbeat", "garage", "uk garage",
        "drum & bass", "dnb", "jungle", "hardstyle", "trap", "phonk", "glitch",
        "synthwave", "eurobeat", "nu disco", "deep house", "tech house",
        "progressive house", "big room", "ambient techno",
        # hip hop / r&b subgenres
        "boom bap", "conscious hip hop", "cloud rap", "emo rap", "drill", "grime",
        "neo soul", "neo-soul", "contemporary r&b", "alternative r&b",
        # jazz / classical subgenres
        "nu jazz", "smooth jazz", "jazz fusion", "swing", "bebop", "big band",
        "acid jazz", "contemporary classical", "modern classical", "baroque",
        "romantic", "minimalism", "piano", "neoclassical", "film score",
        "video game music", "chiptune", "kankyo ongaku", "environmental",
        # metal subgenres
        "heavy metal", "death metal", "black metal", "thrash metal", "doom metal",
        "power metal", "progressive metal", "metalcore", "deathcore", "nu metal",
        "symphonic metal", "folk metal", "djent",
        # folk / country / world
        "singer-songwriter", "acoustic", "americana", "bluegrass", "celtic",
        "flamenco", "bossa nova", "samba", "salsa", "cumbia", "reggaeton",
        "dancehall", "dub", "ethereal",
        # moods that double as genres
        "ambient pop", "atmospheric", "soundscape",
    }
)
