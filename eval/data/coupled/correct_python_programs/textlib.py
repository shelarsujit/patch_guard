"""Shared text helpers.

Imported by slugify, initials and split_sentences. Any change here is a change
to all three, which is the point of this module existing.
"""


def normalize(text):
    """Collapse runs of whitespace and lowercase.

    Punctuation is deliberately PRESERVED -- callers that want it removed are
    responsible for removing it themselves. `initials` and `split_sentences`
    both depend on punctuation surviving this call.

    Input:
        text: a str

    Output:
        The string lowercased, with leading/trailing whitespace stripped and
        internal runs of whitespace collapsed to a single space.

    Examples:
        >>> normalize("  Ada   M. Lovelace ")
        'ada m. lovelace'
    """
    return " ".join(text.lower().split())
