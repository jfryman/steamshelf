import pytest

from steamshelf.hltb import normalize, title_similarity


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Baldur's Gate 3", "baldurs gate 3"),
        ("Sid Meier's Civilization® V", "sid meiers civilization v"),
        ("The Witcher 3: Wild Hunt - Game of the Year Edition", "the witcher 3 wild hunt"),
        ("DOOM Eternal", "doom eternal"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_shorter_hltb_title_still_matches():
    # HowLongToBeat lists this game without Steam's edition suffix.
    score = title_similarity(normalize("Disco Elysium - The Final Cut"), normalize("Disco Elysium"))
    assert score >= 0.95


def test_sequels_do_not_match_their_predecessor():
    assert title_similarity(normalize("Half-Life"), normalize("Half-Life 2")) < 0.95
    assert title_similarity(normalize("Portal 2"), normalize("Portal")) < 0.95


def test_exact_match_beats_a_prefix_match():
    query = normalize("Portal 2")
    assert title_similarity(query, normalize("Portal 2")) > title_similarity(
        query, normalize("Portal 2: Sixense Perceptual Pack")
    )


def test_a_parenthesised_year_is_not_part_of_the_name():
    # Steam lists this as "System Shock 2 (1999)"; HowLongToBeat as "System Shock 2".
    assert normalize("System Shock® 2 (1999)") == "system shock 2"
    assert title_similarity(normalize("System Shock® 2 (1999)"),
                            normalize("System Shock 2")) >= 0.95


def test_a_bare_year_in_a_title_is_kept():
    assert normalize("FIFA 2003") == "fifa 2003"
    assert title_similarity(normalize("FIFA 2003"), normalize("FIFA 2004")) < 0.95
