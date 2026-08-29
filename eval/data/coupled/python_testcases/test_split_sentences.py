from split_sentences import split_sentences


def test_periods():
    assert split_sentences("One. Two. Three.") == ["one", "two", "three"]


def test_mixed_terminators():
    # Depends on textlib.normalize preserving '.', '!' and '?'.
    assert split_sentences("One. Two! Three?") == ["one", "two", "three"]


def test_ignores_empty_segments():
    assert split_sentences("Only one..") == ["only one"]
