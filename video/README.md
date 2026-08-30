# Submission video

`patch-guard.mp4` — 4:51, 1920x1080, generated end to end by
`python -m video.build_video`. Nothing in it was edited by hand.

- **Slides** are drawn with Pillow from `video/sections.py`.
- **Narration** is synthesized with `edge-tts` (Microsoft's neural voices,
  no API key). No audio was recorded.
- **Assembly** is ffmpeg: one still held for exactly the length of its narration
  plus a 0.4s tail, then concatenated.

Every figure on the slides is copied from `results/report.md`, which is itself
generated from `results/*.jsonl`. If a number changes, regenerate the report,
update `sections.py`, and rebuild — the video is downstream of the measurements,
not a separate account of them.

## Two things the first build got wrong

**The voice.** The first version used the Windows SAPI voice, which is fully
offline but concatenative: it lands every sentence on the same flat contour, and
the narration was written around its mispronunciations — "M C P", "read me",
"twenty four points". Together those made it sound like a machine reciting.
The neural voice carries prosody across a clause and reads acronyms and numerals
correctly, so the script is now ordinary written English. The cost is a network
connection at build time, which is acceptable because the rendered mp4 is
committed and nobody has to rebuild it to watch it.

**The length.** Each segment was cut with `-shortest`, so its video stream ran on
to the next keyframe and the mp3 decoder added its own padding. That overran by
about two seconds per segment — invisible one at a time, nineteen seconds across
ten of them, which turned a 4:47 script into a 5:06 file and put it over the
limit. Segments are now pinned with `-t`, and the duration the build prints is
the duration ffprobe reports.

Rebuild:

    pip install edge-tts pillow
    python -m video.build_video

`video/build/` holds the intermediate PNGs, scripts and MP3s and is disposable.
