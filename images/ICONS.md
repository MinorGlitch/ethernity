# Ethernity icons

`ethernity-mark.svg` is the folded-paper infinity mark. `ethernity-app.svg` places it on a
rounded charcoal tile for desktop icons. Both are editable vector artwork.

`scripts/build_icons.py` exports these files:

- `src/ethernity/resources/icons/app.png`: 1024-pixel desktop icon and browser favicon.
- `src/ethernity/resources/icons/activity.png`: 60 frames at 64 pixels, for the active-task icon.
- `ethernity.ico`: Windows Setup icon, with sizes from 16 through 256 pixels.

The tray animation uses flat vector panels. Two folds travel around the paper loop, narrowing the
strip and exposing its charcoal reverse. The diagonal crossing stays in front. The tray uses
every second frame at 80 milliseconds.
The animation runs only during an active task in the desktop app; otherwise it shows `app.png`.

Run from the repository root:

```sh
uv run --with cairosvg python scripts/build_icons.py
```

CairoSVG needs the system Cairo library. On macOS with Homebrew, set
`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` if the exporter cannot find it.
Neither CairoSVG nor Cairo is an application dependency. PyInstaller converts `app.png` to
native icon formats while packaging.

The README uses a separate animated PNG, `ethernity-animated.png`: a 640 by 338 pixel,
ten-second loop in which the paper unfolds into the infinity mark and folds away.
`ethernity-logo.svg` is its static counterpart. See the
[README media guide](../tooling/demos/README.md#logo) for the source and rebuild command.
