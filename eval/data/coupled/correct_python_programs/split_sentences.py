"""Sentence splitting."""

from textlib import normalize


def split_sentences(text):
    """Split text into sentences on '.', '!' and '?'.

    Depends on `normalize` preserving terminal punctuation -- without the marks
    there is nothing to split on.

    Input:
        text: a str

    Output:
        A list of non-empty, stripped sentence strings.

    Examples:
        >>> split_sentences("One. Two! Three?")
        ['one', 'two', 'three']
    """
    cleaned = normalize(text)
    for mark in "!?":
        cleaned = cleaned.replace(mark, ".")
    return [s.strip() for s in cleaned.split(".") if s.strip()]
