"""Render fresh captured output as branded GIFs and static posters."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = (1200, 730)
BACKGROUND = "#0c1118"
PANEL = "#111923"
LINE = "#2b3745"
TEXT = "#e8eef5"
MUTED = "#9baebe"
AMBER = "#ffbc70"
GREEN = "#9ce0b8"
RED = "#ffa2a2"
GIF_BUDGET = 1_000_000
TOTAL_BUDGET = 3_000_000
ASSETS = Path(__file__).resolve().parents[2] / "docs" / "assets"


def wrapped(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    columns = int(width / font.getlength("M"))
    lines = []
    for line in text.splitlines():
        lines.extend(
            textwrap.wrap(
                line,
                width=columns,
                replace_whitespace=False,
                drop_whitespace=False,
                break_on_hyphens=False,
            )
            or [""]
        )
    return lines


def frame(
    demo: dict,
    version: str,
    index: int,
    command: str,
    output: list[str],
    progress: float,
    fonts: dict[str, ImageFont.FreeTypeFont],
) -> Image.Image:
    image = Image.new("RGB", SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((1, 1, 1198, 728), radius=22, outline=LINE, width=2)
    draw.rounded_rectangle((32, 25, 65, 59), radius=9, fill="#32261d")
    draw.polygon(
        [(49, 29), (45, 40), (38, 47), (42, 54), (53, 54), (59, 47), (52, 38), (50, 46), (46, 44)],
        fill=AMBER,
    )
    draw.text((77, 28), "BlazeCrawl", fill=TEXT, font=fonts["brand"])
    draw.text((200, 34), "CORE", fill=MUTED, font=fonts["small"])
    draw.text((901, 33), f"LOCAL SOURCE CAPTURE / v{version}", fill=MUTED, font=fonts["small"])
    draw.text((32, 83), demo["title"], fill=TEXT, font=fonts["title"])
    draw.text((34, 137), demo["subtitle"], fill=MUTED, font=fonts["body"])

    stages = demo["stages"]
    chip_width = (1136 - 12 * (len(stages) - 1)) // len(stages)
    for number, item in enumerate(stages):
        x = 32 + number * (chip_width + 12)
        active = number == index
        draw.rounded_rectangle(
            (x, 178, x + chip_width, 211),
            radius=8,
            fill="#2b241e" if active else "#141d27",
            outline=AMBER if active else LINE,
        )
        draw.text(
            (x + 13, 184),
            f"0{number + 1}  {item['label']}",
            fill=AMBER if active else MUTED,
            font=fonts["small"],
        )

    draw.rounded_rectangle((32, 232, 1168, 651), radius=14, fill=PANEL, outline=LINE, width=2)
    draw.line((33, 274, 1166, 274), fill=LINE)
    for x, color in ((52, "#ff938a"), (70, "#e8bc73"), (88, "#90caa4")):
        draw.ellipse((x, 249, x + 8, 257), fill=color)
    draw.text((113, 244), "terminal / recorded output", fill=MUTED, font=fonts["small"])
    draw.text((1000, 244), "127.0.0.1", fill=MUTED, font=fonts["small"])

    command_lines = wrapped("$ " + command, fonts["mono"], 1078)
    y = 296
    for line in command_lines:
        draw.text((57, y), line, fill=AMBER, font=fonts["mono"])
        y += 28
    y += 22
    for line in output:
        color = TEXT
        if "url_rejected" in line or "loopback address" in line:
            color = RED
        elif '"completed"' in line or '"ok"' in line or "tools/list" in line:
            color = GREEN
        elif line.startswith("[Learn more]"):
            color = AMBER
        draw.text((57, y), line, fill=color, font=fonts["mono"])
        y += 28
    if y > 642:
        raise ValueError(
            f"{demo['title']}: captured text exceeds the terminal panel; reflow, don't truncate."
        )
    draw.text((34, 668), stages[index]["note"], fill=MUTED, font=fonts["small"])
    draw.line((34, 708, 1166, 708), fill=LINE, width=3)
    end = 34 + int(1132 * (index + progress) / len(stages))
    draw.line((34, 708, end, 708), fill=AMBER, width=3)
    return image


def render_demo(demo: dict, version: str, fonts: dict) -> tuple[list[Image.Image], list[int]]:
    frames = []
    durations = []
    for index, item in enumerate(demo["stages"]):
        command = item["command"]
        output = wrapped(item["output"], fonts["mono"], 1078)
        for length in range(0, len(command), 4):
            frames.append(frame(demo, version, index, command[:length], [], 0.15, fonts))
            durations.append(60)
        for length in range(len(output) + 1):
            frames.append(
                frame(
                    demo,
                    version,
                    index,
                    command,
                    output[:length],
                    0.25 + 0.65 * length / max(1, len(output)),
                    fonts,
                )
            )
            durations.append(100)
        complete = frame(demo, version, index, command, output, 1, fonts)
        frames.append(complete)
        durations.append(9000 if len(demo["stages"]) == 1 else 4200)
        if index + 1 < len(demo["stages"]):
            following = frame(demo, version, index + 1, "", [], 0, fonts)
            for opacity in (0.25, 0.5, 0.75):
                frames.append(Image.blend(complete, following, opacity))
                durations.append(80)
    return frames, durations


def verify(path: Path) -> dict:
    with Image.open(path) as image:
        if image.n_frames < 2 or image.size != SIZE:
            raise ValueError(f"{path.name}: expected a full-size animated GIF.")
        duration = 0
        for index in range(image.n_frames):
            image.seek(index)
            duration += image.info["duration"]
        if not 10_000 <= duration <= 20_000:
            raise ValueError(f"{path.name}: duration {duration}ms is outside the 10-20s budget.")
        if path.stat().st_size > GIF_BUDGET:
            raise ValueError(f"{path.name}: exceeds the {GIF_BUDGET}-byte GIF budget.")
        return {
            "file": path.name,
            "frames": image.n_frames,
            "seconds": duration / 1000,
            "bytes": path.stat().st_size,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--mono", required=True, type=Path, help="Installed monospace TTF")
    parser.add_argument("--sans", required=True, type=Path, help="Installed regular sans-serif TTF")
    parser.add_argument("--bold", required=True, type=Path, help="Installed bold sans-serif TTF")
    parser.add_argument("--assets", type=Path, default=ASSETS)
    args = parser.parse_args()
    fonts = {
        "mono": ImageFont.truetype(str(args.mono), 22),
        "body": ImageFont.truetype(str(args.sans), 21),
        "small": ImageFont.truetype(str(args.sans), 16),
        "brand": ImageFont.truetype(str(args.bold), 23),
        "title": ImageFont.truetype(str(args.bold), 42),
    }
    captured = json.loads(args.capture.read_text(encoding="utf-8"))
    reports = []
    with tempfile.TemporaryDirectory(prefix="blazecrawl-media-") as temporary:
        work = Path(temporary)
        for name in ("hero", "map-crawl", "mcp", "security"):
            demo = captured["demos"][name]
            if fonts["title"].getlength(demo["title"]) > 1136:
                raise ValueError(f"{name}: title is too wide.")
            frames, durations = render_demo(demo, captured["version"], fonts)
            gif = work / f"blazecrawl-{name}.gif"
            poster = work / f"blazecrawl-{name}.png"
            frames[-1].save(poster, optimize=True)
            palette_source = Image.new("RGB", (SIZE[0], SIZE[1] * len(demo["stages"])))
            for index, item in enumerate(demo["stages"]):
                complete = frame(
                    demo,
                    captured["version"],
                    index,
                    item["command"],
                    wrapped(item["output"], fonts["mono"], 1078),
                    1,
                    fonts,
                )
                palette_source.paste(complete, (0, SIZE[1] * index))
            palette = palette_source.quantize(colors=128)
            indexed = [item.quantize(palette=palette, dither=Image.Dither.NONE) for item in frames]
            indexed[0].save(
                gif,
                save_all=True,
                append_images=indexed[1:],
                duration=durations,
                loop=1,
                disposal=1,
                optimize=True,
            )
            reports.append(verify(gif))
        total = sum(path.stat().st_size for path in work.iterdir())
        total += sum(path.stat().st_size for path in args.assets.glob("blazecrawl-brand*.svg"))
        if total > TOTAL_BUDGET:
            raise ValueError(
                f"README assets total {total} bytes exceeds the {TOTAL_BUDGET}-byte budget."
            )
        args.assets.mkdir(parents=True, exist_ok=True)
        for path in work.iterdir():
            shutil.copyfile(path, args.assets / path.name)
    print(json.dumps({"assets": reports, "total_bytes": total}, indent=2))


if __name__ == "__main__":
    main()
