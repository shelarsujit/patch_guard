from textlib import normalize


def test_lowercases_and_collapses():
    assert normalize("  Ada   M. Lovelace ") == "ada m. lovelace"


def test_preserves_punctuation():
    # This is the contract the other three modules rely on.
    assert normalize("Hello, World!") == "hello, world!"
