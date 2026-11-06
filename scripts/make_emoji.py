"""Render still and rotating assistant logos for Slack."""

from io import BytesIO
from pathlib import Path

import cairosvg
from PIL import Image

out = Path(__file__).resolve().parents[1] / "assets"


def render(name, filename):
    source = Image.open(
        BytesIO(
            cairosvg.svg2png(
                url=str(out / filename), output_width=1024, output_height=1024
            )
        )
    ).convert("RGBA")
    source = source.crop(source.getbbox())
    source.thumbnail((360, 360), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (512, 512))
    canvas.alpha_composite(
        source, ((512 - source.width) // 2, (512 - source.height) // 2)
    )
    canvas.resize((128, 128), Image.Resampling.LANCZOS).save(out / f"{name}.png")
    frames = []
    for frame in range(40):
        rotated = canvas.rotate(-frame * 9, Image.Resampling.BICUBIC).resize(
            (128, 128), Image.Resampling.LANCZOS
        )
        # GIF has binary transparency. Use a fixed palette to keep each frame stable.
        alpha = rotated.getchannel("A")
        result = Image.new("P", (128, 128), 0)
        result.putpalette([255, 255, 255, 0, 0, 0] + [0, 0, 0] * 254)
        result.paste(1, mask=alpha.point(lambda value: 255 if value >= 96 else 0))
        result.info["transparency"] = 0
        frames.append(result)
    frames[0].save(
        out / f"{name}_working.gif",
        save_all=True,
        append_images=frames[1:],
        duration=50,
        loop=0,
        transparency=0,
        disposal=2,
        optimize=False,
    )
    with Image.open(out / f"{name}_working.gif") as gif:
        assert gif.size == (128, 128) and gif.n_frames == 40
        gif.convert("RGBA").save(out / f"{name}_working-preview.png")
    assert (out / f"{name}_working.gif").stat().st_size < 128 * 1024
    print(
        "Created 40-frame clockwise rotation, 2 seconds per turn:",
        (out / f"{name}_working.gif").stat().st_size,
        "bytes",
    )


with Image.open(out / "codex_working.gif") as codex:
    codex.convert("RGBA").save(out / "codex.png")
render("claude", "anthropic.svg")
