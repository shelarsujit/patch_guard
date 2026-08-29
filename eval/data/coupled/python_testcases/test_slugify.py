from slugify import slugify


def test_plain_words():
    assert slugify("Hello World") == "hello-world"


def test_collapses_whitespace():
    assert slugify("  Hello   World  ") == "hello-world"


def test_strips_punctuation():
    # The reported bug: punctuation survives into the slug.
    assert slugify("Hello, World!") == "hello-world"


def test_strips_punctuation_mid_name():
    assert slugify("Ada M. Lovelace") == "ada-m-lovelace"
