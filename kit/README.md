# Browser recovery kit

The lean and scanner builds use the same app and recovery engine. Build aliases
include the camera implementation only in the scanner variant. Generated files
in `dist/` and the Python package resources are build outputs.

## State and recovery

- `app.js` owns one state value and dispatches actions synchronously.
  `ui/` builds the fixed interface once and updates existing elements. User data
  enters the page through textContent/value, never HTML interpolation.
- `scanner/` owns camera start, stop, and disposal. Locking the kit, resetting, or
  leaving the page stops the camera. Late camera requests cannot restart it.
- The reducer accepts patches and resets. Each accepted change advances the
  revision, including resets. Patches copy the mutable records they contain;
  fields outside the patch keep their identity.
- Collection actions parse input synchronously and queue verification. Verification
  works on a copy and publishes only collection-owned fields. If another
  collection changes the records, its queued verification handles the newer data.
  Text edits do not invalidate verification or get overwritten by it.
- Recovery uses a request ID derived from the revision. Cancelling, changing input,
  or resetting makes old completions ineligible to publish results.
- `recovery_input.js` assesses whether recovery can start. Controls and actions
  share this assessment. Document collection checks live in `frames_cipher.js`;
  neither replaces the recovery engine's identity, signature, format, and resource
  checks.
- The page and recovery worker use the same compiled script, so crypto dependencies
  are included once. The worker owns expensive recovery work and is terminated
  on cancellation or completion.

## Checks

From this directory, run `npm run lint`, `npm run format:check`, and `npm test`.
For changes affecting the generated kit, run `node build_kit.mjs` followed by
`npm run test:browser -- chromium firefox webkit`. This checks both variants in
all three browsers. Keep the frozen recovery fixtures and negative-path tests
when changing coordination code.

The browser checks cover the actual generated kits, printed-loader metadata,
legacy recovery fixtures, scanner images, and camera cancellation races. UI
lifecycle checks use browser DOM elements; there is no simulated DOM renderer.
