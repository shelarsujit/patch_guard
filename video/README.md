# Submission video

`patch-guard.mp4` — 4:48, 1920x1080, generated end to end by
`python -m video.build_video`. Nothing in it was edited by hand.

- **Slides** are drawn with Pillow from `video/sections.py`.
- **Narration** is synthesized offline with the Windows SAPI voice. No service,
  no key, no audio recording.
- **Assembly** is ffmpeg: one still held for exactly the length of its narration,
  then concatenated.

Every figure on the slides is copied from `results/report.md`, which is itself
generated from `results/*.jsonl`. If a number changes, regenerate the report,
update `sections.py`, and rebuild — the video is downstream of the measurements,
not a separate account of them.

Rebuild:

    python -m video.build_video

`video/build/` holds the intermediate PNGs and WAVs and is disposable.
