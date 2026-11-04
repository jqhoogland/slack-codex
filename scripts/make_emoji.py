"""Create a small robot with a rotating progress ring for Slack."""

import math
from pathlib import Path

from PIL import Image, ImageDraw

out = Path(__file__).resolve().parents[1] / "assets"
out.mkdir(exist_ok=True)
frames = []
for frame in range(24):
    im = Image.new("RGB", (128, 128), (255, 0, 255))
    draw = ImageDraw.Draw(im)
    for dot in range(12):
        angle = 2 * math.pi * (dot / 12 + frame / 24)
        x, y = 64 + 53 * math.cos(angle), 64 + 53 * math.sin(angle)
        color = (12 + dot * 2, 90 + dot * 9, 110 + dot * 10)
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color)
    draw.line((64, 31, 64, 42), fill="#142c3b", width=5)
    draw.ellipse((59, 26, 69, 36), fill="#10a37f")
    draw.rounded_rectangle((29, 40, 99, 94), radius=13, fill="#142c3b")
    draw.rounded_rectangle((34, 45, 94, 89), radius=9, fill="#f4fbff")
    draw.ellipse((43, 56, 53, 66), fill="#142c3b")
    draw.ellipse((75, 56, 85, 66), fill="#142c3b")
    draw.rounded_rectangle((46, 76, 82, 81), radius=2, fill="#10a37f")
    im = im.convert("P", palette=Image.Palette.ADAPTIVE, colors=64)
    palette = im.getpalette()
    transparent = next(
        i for i in range(256) if palette[i * 3 : i * 3 + 3] == [255, 0, 255]
    )
    im.info["transparency"] = transparent
    frames.append(im)
frames[0].save(
    out / "codex_working.gif",
    save_all=True,
    append_images=frames[1:],
    duration=80,
    loop=0,
    disposal=2,
    optimize=False,
)
with Image.open(out / "codex_working.gif") as preview:
    preview.convert("RGBA").save(out / "codex_working-preview.png")
with Image.open(out / "codex_working.gif") as gif:
    assert gif.size == (128, 128) and gif.n_frames == 24
assert (out / "codex_working.gif").stat().st_size < 128 * 1024
print(
    "Created codex_working.gif:",
    (out / "codex_working.gif").stat().st_size,
    "bytes; 24 frames; 128 x 128",
)
