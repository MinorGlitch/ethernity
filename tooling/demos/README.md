# README media

## Backup demo

The demo runs the real terminal app through a [VHS](https://github.com/charmbracelet/vhs)
tape. It selects two synthetic files, keeps the default two-of-three recovery setup,
creates the PDFs, and runs the app's recovery check. The recording has no caption overlays;
pauses give viewers time to read each step. The terminal is 112 columns by 36 rows so the app
uses its desktop layout and full-height controls. The final six seconds show the encrypted
backup and all three recovery sheets from that run. The walkthrough takes about one minute.

### Record

Install VHS 0.12.1 or newer, `ttyd`, and FFmpeg. On macOS, `brew install vhs`
installs all three. Use the repository's Python environment with its locked dependencies.

From the repository root:

```sh
uv run python tooling/demos/record_backup.py
```

The recording uses a temporary folder, synthetic files, and a separate configuration.
It does not load your Ethernity settings or personal files. The runner restores the
generated backup through the CLI using exactly two recovery sheets and compares both
recovered files byte for byte. It rejects recordings that lack the UI's successful
recovery check or contain the operator's home directory.

Outputs are saved in `build/readme-demo/`:

- `backup_flow.gif` and `backup_flow.mp4`: the complete demo.
- `terminal_app_preview.png`: a static view of the recovery options.
- `ending.png` and `checked.png`: page previews and the successful recovery check.
- `terminal.ascii` and `verification.json`: text for review and verification results.

VHS uses Menlo, with DejaVu Sans Mono and the system monospace font as fallbacks.
The final frame uses the repository's Public Sans fonts. Processing waits are shortened;
the animation is an overview, not a timing benchmark. It checks generated PDFs, not
physical prints or camera scans.

### Update the README assets

Watch the entire animation and inspect the static preview at the README's display size.
Check that each step is readable, the recovery check succeeds, and no personal paths
appear. Then copy the reviewed outputs:

```sh
cp build/readme-demo/backup_flow.gif images/readme/backup_flow.gif
cp build/readme-demo/terminal_app_preview.png images/readme/terminal_app_preview.png
```

Keep the video and verification intermediates in the ignored build directory.
Edit `backup.tape` for navigation and pacing; edit `record_backup.py` for sample files
and the final PDF preview. No application code or test fixtures are changed by recording.

## Logo

The README shows `images/ethernity-animated.png` below the status badges, followed by the
introduction and backup walkthrough. The logo is a transparent, 640 by 338 pixel animated PNG.
The paper assembles into the infinity mark, holds, and folds away over ten seconds.
The first and last frames are blank. Clicking the logo opens the static
`images/ethernity-logo.svg`.

The renderer draws at four times the output resolution, then downsamples with alpha-aware
filtering. Animated PNG preserves the partially transparent edge pixels; GIF would discard
them and leave jagged edges. The 640-pixel asset displays at 320 pixels in the README.

To rebuild, install the kit's Node dependencies and Playwright Chromium, plus FFmpeg
on your PATH. From the repository root:

```sh
node tooling/demos/render_logo.mjs
```

Inspect `build/readme-logo/paper-assembly/ribbon.png` on light and dark backgrounds, then
copy the reviewed output:

```sh
cp build/readme-logo/paper-assembly/ribbon.png images/ethernity-animated.png
```

Frames and intermediate files stay in the ignored build directory. The desktop icons
and tray animation are exported separately by `scripts/build_icons.py`.
