# README backup demo

The demo runs the real terminal app through a [VHS](https://github.com/charmbracelet/vhs)
tape. It selects two synthetic files, keeps the default two-of-three recovery setup,
creates the PDFs, and runs the app's recovery check. Five short captions guide the viewer,
with reading pauses at each step. The terminal is 112 columns by 36 rows so the app uses
its desktop layout and full-height controls. The final ten seconds show pages from
that same backup. The complete walkthrough takes about 80 seconds.

## Record

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
- `chapters.json`: caption start times, matched to screenshots of the recorded screens.

VHS uses Menlo, with DejaVu Sans Mono and the system monospace font as fallbacks.
Captions and the final frame use the repository's Public Sans fonts. Processing waits are shortened;
the animation is an overview, not a timing benchmark. It checks generated PDFs, not
physical prints or camera scans.

## Update the README assets

Watch the entire animation and inspect the static preview at the README's display size.
Check that each step is readable, the recovery check succeeds, and no personal paths
appear. Then copy the reviewed outputs:

```sh
cp build/readme-demo/backup_flow.gif images/readme/backup_flow.gif
cp build/readme-demo/terminal_app_preview.png images/readme/terminal_app_preview.png
```

Keep the video and verification intermediates in the ignored build directory.
Edit `backup.tape` for navigation and pacing; edit `record_backup.py` for sample files,
captions, and the final PDF preview. No application code or test fixtures are changed by recording.
