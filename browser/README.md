# Local browser client

This is the terminal adapter for `ethernity --web`. The screens and task logic still run
in the same Python Textual app as the terminal interface. The standalone recovery kit
is separate and lives in `kit/`.

The client uses xterm's public APIs and Textual's existing WebSocket protocol. Wheel
distance is converted into standard SGR mouse reports, including fractional trackpad
movement, horizontal scrolling and line/page delta units. Reports are batched once per
animation frame and flushed before keyboard or pointer input. No app state lives here.

The client uses xterm's standard DOM renderer. WebGL added repeated rendering pauses
in Chromium with software graphics during sustained scrolling. There is no GPU renderer
or renderer switching to maintain. This replaces textual-serve's bundled frontend,
which reduced each wheel event to one scroll report and loaded both WebGL and canvas
renderers.

Run these commands from this directory:

```sh
npm ci
npm test
npm run lint
npm run format:check
npm run build
npm run test:browser -- chromium firefox webkit
```

The generated files in `src/ethernity/app/browser/static/` are checked in so installing
from a wheel, source archive or standalone binary requires no Node.js or network access.
Rebuild them after changing the client or its dependencies. `npm run check` verifies
that the checked-in assets match the source and lockfile. The browser tests exercise the
built assets in Chromium, Firefox and WebKit.
