"""Record a real backup with VHS, verify its files, and add a PDF preview ending."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pypdfium2 as pdfium
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps, ImageStat

ROOT = Path(__file__).resolve().parents[2]
FONTS = ROOT / "src/ethernity/resources/designs/_shared/assets/fonts"
BACKGROUND = "#171918"
FOREGROUND = "#EAE6DA"
MUTED = "#A7AA99"
ACCENT = "#E0B56D"
CAPTION_HEIGHT = 120
CHAPTERS = (
    (None, "1. Choose your files", "Add the small files you want to keep on paper."),
    (
        "recovery.png",
        "2. Choose how to recover them",
        "Three recovery sheets. Any two can unlock this backup.",
    ),
    (
        "print.png",
        "3. Set up the printed backup",
        "Choose the paper size, print design, and a folder for the PDFs.",
    ),
    (
        "review.png",
        "4. Review and create",
        "Check your choices, then create the encrypted backup.",
    ),
    (
        "success.png",
        "5. Check that recovery works",
        "Restore from the generated PDFs using two recovery sheets.",
    ),
)
SAMPLE_FILES = {
    "recovery-notes.txt": (
        "Demonstration files only. No real secrets.\n\n"
        "Keep recovery sheets in separate places.\n"
        "Test recovery before relying on a printed backup.\n"
    ),
    "vault.conf": '[archive]\nname = "Family records"\nstorage = "offline"\n',
}


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def prepare(directory: Path) -> dict[str, str]:
    documents = directory / "work/documents"
    documents.mkdir(parents=True)
    for name, contents in SAMPLE_FILES.items():
        (documents / name).write_text(contents, encoding="utf-8")
    config = directory / "config/ethernity/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[render]\nstyle = "sentinel"\n[page]\nsize = "A4"\n', encoding="utf-8")
    env = dict(os.environ)
    env.pop("NO_COLOR", None)
    env.pop("TEXTUAL_THEME", None)
    env.pop("TEXTUAL_DRIVER", None)
    env["COLORTERM"] = "truecolor"
    env["XDG_CONFIG_HOME"] = str(config.parent.parent)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def verify(directory: Path, env: dict[str, str]) -> Path:
    transcript = (directory / "terminal.ascii").read_text(encoding="utf-8")
    if not all(
        message in transcript
        for message in ("PDF check passed", "2 files recovered using 2 recovery sheets")
    ):
        raise RuntimeError("The recorded UI did not complete the recovery check.")
    if str(Path.home()) in transcript:
        raise RuntimeError("The recording contains a real home directory.")
    backups = list((directory / "work/paper-backup").glob("backup-*"))
    if len(backups) != 1:
        raise RuntimeError(f"Expected one backup, found {len(backups)}.")
    backup = backups[0]
    sheets = sorted(backup.glob("shard-*.pdf"))
    if len(sheets) != 3:
        raise RuntimeError("Expected three recovery sheets.")
    restored = directory / "restored"
    run(
        [
            sys.executable,
            "-m",
            "ethernity",
            "run",
            "restore",
            "--scan",
            str(backup / "qr_document.pdf"),
            "--recovery-document",
            str(sheets[0]),
            "--recovery-document",
            str(sheets[1]),
            "--output",
            str(restored),
            "--yes",
        ],
        cwd=directory,
        env=env,
    )
    actual = {
        path.relative_to(restored).as_posix(): path.read_bytes()
        for path in restored.rglob("*")
        if path.is_file()
    }
    expected = {name: content.encode("utf-8") for name, content in SAMPLE_FILES.items()}
    if actual != expected:
        raise RuntimeError("Restored files do not match the demonstration inputs.")
    return backup


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "PublicSans-Black.ttf" if bold else "PublicSans-Regular.ttf"
    return ImageFont.truetype(str(FONTS / name), size)


def page_preview(path: Path, size: tuple[int, int]) -> Image.Image:
    with pdfium.PdfDocument(path) as document:
        page = document[0]
        bitmap = page.render(scale=2)
        image = bitmap.to_pil().convert("RGB")
        bitmap.close()
        page.close()
    return ImageOps.contain(image, size, Image.Resampling.LANCZOS)


def make_ending(backup: Path, directory: Path, size: tuple[int, int]) -> None:
    width, height = size
    canvas = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    draw.text((48, 30), "Ready to print", font=font(36, bold=True), fill=FOREGROUND)
    draw.text((width - 48, 42), "ETHERNITY / BACKUP DEMO", font=font(18), fill=ACCENT, anchor="ra")
    draw.line((48, 94, width - 48, 94), fill="#3B3E34", width=2)

    gap = 38
    available_height = height - 278
    page_width = min(int(available_height * 210 / 297), (width - 96 - gap * 2) // 3)
    page_height = int(page_width * 297 / 210)
    left = (width - (page_width * 3 + gap * 2)) // 2
    sheets = sorted(backup.glob("shard-*.pdf"))
    pages = [backup / "qr_document.pdf", sheets[0], sheets[1]]
    labels = ["Encrypted backup", "Recovery sheet 1 of 3", "Recovery sheet 2 of 3"]
    for index, (path, label) in enumerate(zip(pages, labels, strict=True)):
        preview = page_preview(path, (page_width, page_height))
        x = left + index * (page_width + gap)
        y = 124 + (available_height - page_height) // 2
        draw.rectangle((x - 1, y - 1, x + preview.width, y + preview.height), fill="#555A4D")
        canvas.paste(preview, (x, y))
        draw.text(
            (x + page_width / 2, y + page_height + 18),
            label,
            font=font(21),
            fill=FOREGROUND,
            anchor="ma",
        )
    draw.text(
        (width / 2, height - 84),
        "Keep recovery sheets separate. Any 2 of 3 unlock your files.",
        font=font(25),
        fill=ACCENT,
        anchor="ma",
    )
    draw.text(
        (width / 2, height - 43),
        "Generated PDFs checked. Test your printed copies before storing them.",
        font=font(20),
        fill=MUTED,
        anchor="ma",
    )
    canvas.save(directory / "ending.png")


def chapter_times(directory: Path, env: dict[str, str]) -> list[float]:
    """Locate the recorded screens so captions follow the UI, including variable waits."""
    samples = directory / "samples"
    samples.mkdir()
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "terminal.mp4",
            "-vf",
            "fps=5,scale=320:-1",
            "samples/%05d.png",
        ],
        cwd=directory,
        env=env,
    )
    frames = []
    for path in sorted(samples.glob("*.png")):
        with Image.open(path) as frame:
            frames.append(frame.convert("RGB"))
    starts = [0.0]
    previous = 0
    for marker, _, _ in CHAPTERS[1:]:
        assert marker is not None
        with Image.open(directory / marker) as screenshot:
            target = screenshot.convert("RGB").resize(frames[0].size, Image.Resampling.LANCZOS)
        scores = [
            sum(ImageStat.Stat(ImageChops.difference(frame, target)).mean) / 3
            for frame in frames[previous:]
        ]
        best = min(scores)
        if best > 4:
            raise RuntimeError(f"Could not locate the {marker} screen in the recording.")
        # Use the first matching frame, rather than a later identical frame in the reading pause.
        previous += next(index for index, score in enumerate(scores) if score <= best + 0.25)
        starts.append(previous / 5)
    return starts


def caption_video(directory: Path, size: tuple[int, int], env: dict[str, str]) -> None:
    starts = chapter_times(directory, env)
    width, _ = size
    inputs = ["-i", "terminal.mp4"]
    filters = [f"[0:v]pad=iw:ih+{CAPTION_HEIGHT}:0:{CAPTION_HEIGHT}:color={BACKGROUND}[base]"]
    for index, (_, title, description) in enumerate(CHAPTERS):
        caption = Image.new("RGB", (width, CAPTION_HEIGHT), BACKGROUND)
        draw = ImageDraw.Draw(caption)
        draw.text((36, 17), title, font=font(36, bold=True), fill=FOREGROUND)
        draw.text((36, 65), description, font=font(28), fill=MUTED)
        draw.line((24, CAPTION_HEIGHT - 2, width - 24, CAPTION_HEIGHT - 2), fill=ACCENT, width=2)
        name = f"caption-{index}.png"
        caption.save(directory / name)
        inputs.extend(["-loop", "1", "-i", name])
        end = f"*lt(t,{starts[index + 1]})" if index + 1 < len(starts) else ""
        filters.append(
            f"[{'base' if index == 0 else f'captioned{index - 1}'}][{index + 1}:v]"
            f"overlay=shortest=1:enable='gte(t,{starts[index]}){end}'[captioned{index}]"
        )
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[captioned{len(CHAPTERS) - 1}]",
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "captioned.mp4",
        ],
        cwd=directory,
        env=env,
    )
    (directory / "chapters.json").write_text(
        json.dumps(
            [
                {"start": start, "title": chapter[1]}
                for start, chapter in zip(starts, CHAPTERS, strict=True)
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def export(directory: Path, output: Path, env: dict[str, str]) -> None:
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "captioned.mp4",
            "-loop",
            "1",
            "-framerate",
            "15",
            "-t",
            "10",
            "-i",
            "ending.png",
            "-filter_complex",
            "[0:v]fps=15,setsar=1,setpts=PTS-STARTPTS[a];"
            "[1:v]fps=15,setsar=1,setpts=PTS-STARTPTS,fade=t=in:d=0.2[b];"
            "[a][b]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "backup_flow.mp4",
        ],
        cwd=directory,
        env=env,
    )
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            "backup_flow.mp4",
            "-filter_complex",
            "fps=15,scale=1200:-2:flags=lanczos,split[a][b];"
            "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle",
            "-loop",
            "0",
            "backup_flow.gif",
        ],
        cwd=directory,
        env=env,
    )
    output.mkdir(parents=True, exist_ok=True)
    for name in (
        "backup_flow.gif",
        "backup_flow.mp4",
        "ending.png",
        "checked.png",
        "terminal.ascii",
        "chapters.json",
    ):
        shutil.copyfile(directory / name, output / name)
    with Image.open(directory / "recovery.png") as preview:
        canvas = Image.new("RGB", (preview.width, preview.height + CAPTION_HEIGHT), BACKGROUND)
        with Image.open(directory / "caption-1.png") as caption:
            canvas.paste(caption, (0, 0))
        canvas.paste(preview, (0, CAPTION_HEIGHT))
        canvas.save(output / "terminal_app_preview.png")
    (output / "verification.json").write_text(
        json.dumps(
            {
                "files_matched": sorted(SAMPLE_FILES),
                "recovery_sheets_used": 2,
                "recovery_sheets_created": 3,
                "personal_home_path_found": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/readme-demo")
    args = parser.parse_args()
    for program in ("vhs", "ffmpeg", "ttyd"):
        if shutil.which(program) is None:
            parser.error(f"Install {program} before recording the demo.")
    output = args.output.resolve()
    # A short temporary path keeps personal directories out of every recorded screen.
    temporary_parent = Path("/tmp") if Path("/tmp").is_dir() else None
    with TemporaryDirectory(prefix="ethernity-demo-", dir=temporary_parent) as temporary:
        directory = Path(temporary)
        env = prepare(directory)
        run(["vhs", str(Path(__file__).with_name("backup.tape"))], cwd=directory, env=env)
        backup = verify(directory, env)
        with Image.open(directory / "review.png") as preview:
            size = preview.size
        caption_video(directory, size, env)
        make_ending(backup, directory, (size[0], size[1] + CAPTION_HEIGHT))
        export(directory, output, env)
    print(f"Verified demo saved to {output}")


if __name__ == "__main__":
    main()
