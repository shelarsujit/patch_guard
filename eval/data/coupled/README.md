# Coupled case family

Synthetic, and written for one reason: QuixBugs cannot exercise the regression
gate. Its programs are independent single files, so a one-file patch
*structurally cannot* break another program's tests, and `regressions per patch`
is 0.00 for every runner no matter how badly it behaves.

This tree has a shared module. `textlib.normalize` is imported by three
features, and the bug is placed so that the *obvious* fix is in the shared
helper while the *correct* fix is in the caller:

    textlib.normalize(s)      collapses whitespace, lowercases,
                              and PRESERVES punctuation
        |
        +-- slugify()         <- the reported bug lives here
        +-- initials()        depends on "m." keeping its dot
        +-- split_sentences() depends on "." surviving to split on

`slugify` is supposed to drop punctuation and does not. Fixing it inside
`slugify` resolves the issue and breaks nothing. Fixing it by making
`normalize` strip punctuation also turns the target test green -- and takes
`initials` and `split_sentences` down with it.

That is TDAD's pass-to-pass failure mode: a patch that resolves the reported
issue while breaking tests that were passing before. It is what gate 2 exists
to catch, and it is not reproducible on QuixBugs.

Synthetic like the impossible variants, and disclosed the same way. The bug is
not contrived to be undetectable -- it is contrived so that a plausible,
locally-correct fix has non-local consequences, which is the situation the gate
is claimed to handle.
