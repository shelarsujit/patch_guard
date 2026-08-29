from initials import initials


def test_simple_name():
    assert initials("Ada Lovelace") == "a.l."


def test_middle_initial_keeps_its_dot():
    # Depends on textlib.normalize preserving punctuation.
    assert initials("Ada M. Lovelace") == "a.m.l."


def test_extra_whitespace():
    assert initials("  Grace   Brewster  Hopper ") == "g.b.h."
