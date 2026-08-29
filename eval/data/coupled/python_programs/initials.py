"""Initials from a personal name."""

from textlib import normalize


def initials(name):
    """Reduce a name to dotted initials.

    A name part that is already an initial (a single letter followed by a dot)
    keeps its dot rather than gaining a second one, so this depends on
    `normalize` leaving punctuation alone.

    Input:
        name: a str

    Output:
        A str of dotted initials.

    Examples:
        >>> initials("Ada M. Lovelace")
        'a.m.l.'
    """
    out = []
    for part in normalize(name).split():
        letter = part[0]
        out.append(letter + ".")
    return "".join(out)
