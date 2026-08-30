"""Render the submission video: slides + synthesized narration, no manual editing.

Everything here is generated from the repository's own committed numbers. Slides
are drawn with Pillow, narration is synthesized with the Windows SAPI voice, and
ffmpeg muxes one still per section against its audio and concatenates the lot.

    python video/build_video.py

Output: video/patch-guard.mp4
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "video"
BUILD = OUT / "build"

W, H = 1920, 1080
BG = (13, 17, 23)
FG = (230, 237, 243)
DIM = (139, 148, 158)
ACCENT = (63, 185, 80)
WARN = (248, 81, 73)

FONTS = Path("C:/Windows/Fonts")


def font(name: str, size: int):
    for candidate in (FONTS / name, FONTS / name.lower()):
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size)


TITLE_F = font("segoeuib.ttf", 62)
BODY_F = font("segoeui.ttf", 40)
MONO_F = font("consola.ttf", 34)
SMALL_F = font("segoeui.ttf", 28)


def ffmpeg() -> str:
    local = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    for exe in local.rglob("ffmpeg.exe"):
        return str(exe)
    return "ffmpeg"


FFMPEG = ffmpeg()


# --- slides -----------------------------------------------------------------


def slide(path: Path, title: str, lines: list[tuple[str, str]], footer: str = "") -> None:
    """lines: (style, text) where style is body | mono | good | bad | dim."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Shrink an over-long title until it fits the frame rather than letting it
    # run off the right edge.
    tf = TITLE_F
    while tf.size > 30 and d.textlength(title, font=tf) > W - 220:
        tf = font("segoeuib.ttf", tf.size - 3)
    d.text((110, 90 + (TITLE_F.size - tf.size) // 2), title, font=tf, fill=FG)
    d.line([(110, 185), (W - 110, 185)], fill=(48, 54, 61), width=3)

    y = 250
    for style, text in lines:
        if style == "gap":
            y += 34
            continue
        f = MONO_F if style in ("mono", "good", "bad") else BODY_F
        colour = {"good": ACCENT, "bad": WARN, "dim": DIM}.get(style, FG)
        for chunk in textwrap.wrap(text, width=88 if f is not MONO_F else 96) or [""]:
            d.text((110, y), chunk, font=f, fill=colour)
            y += f.size + 16

    if footer:
        d.text((110, H - 90), footer, font=SMALL_F, fill=DIM)
    img.save(path)


# --- narration --------------------------------------------------------------


def narrate(path: Path, text: str) -> None:
    """Synthesize with the Windows SAPI voice (offline, no service)."""
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.SelectVoice('Microsoft Zira Desktop'); "
        "$s.Rate = 2; "
        f"$s.SetOutputToWaveFile('{path}'); "
        f"$s.Speak(@'\n{text}\n'@); "
        "$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   check=True, capture_output=True)


def duration(path: Path) -> float:
    out = subprocess.run(
        [FFMPEG.replace("ffmpeg.exe", "ffprobe.exe"), "-v", "error",
         "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def segment(index: int, png: Path, wav: Path) -> Path:
    """One still image held for exactly the length of its narration."""
    mp4 = BUILD / f"seg{index:02d}.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-loop", "1", "-i", str(png), "-i", str(wav),
         "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest",
         "-vf", "fps=30", str(mp4)],
        check=True, capture_output=True)
    return mp4


# --- assembly ---------------------------------------------------------------

from video.sections import SECTIONS  # noqa: E402


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    segments = []
    total = 0.0

    for i, s in enumerate(SECTIONS):
        png = BUILD / f"slide{i:02d}.png"
        wav = BUILD / f"say{i:02d}.wav"
        slide(png, s["title"], s["lines"], s.get("footer", ""))
        narrate(wav, s["say"])
        secs = duration(wav)
        total += secs
        print(f"  {i:02d}  {secs:5.1f}s  " + s["title"][:58])
        segments.append(segment(i, png, wav))

    listing = BUILD / "concat.txt"
    listing.write_text("".join("file " + repr(p.as_posix()) + chr(10) for p in segments),
                       encoding="utf-8")

    final = OUT / "patch-guard.mp4"
    subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", str(final)], check=True, capture_output=True)

    mins, rem = divmod(int(round(total)), 60)
    print(chr(10) + f"wrote {final}  ({mins}:{rem:02d})")
    if total > 300:
        print("WARNING: over the 5-minute limit -- trim narration")


if __name__ == "__main__":
    main()
