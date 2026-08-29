"""URL slug generation."""

from textlib import normalize

_PUNCTUATION = ".,:;!?'\"()[]{}"


def slugify(text):
    """Turn a title into a URL slug.

    Lowercased, punctuation removed, spaces replaced with single hyphens.

    Input:
        text: a str

    Output:
        A slug: lowercase alphanumerics and hyphens only.

    Examples:
        >>> slugify("Hello, World!")
        'hello-world'
        >>> slugify("Ada M. Lovelace")
        'ada-m-lovelace'
    """
    cleaned = normalize(text)
    return "-".join(cleaned.split())
