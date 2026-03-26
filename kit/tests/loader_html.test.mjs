import assert from "node:assert/strict";
import test from "node:test";

import { buildCompressedLoaderHtml, buildUnsupportedLoaderHtml } from "../lib/loader_html.js";

test("buildUnsupportedLoaderHtml renders an explicit recovery fallback page", () => {
  const html = buildUnsupportedLoaderHtml();

  assert.match(html, /Recovery kit cannot open here/);
  assert.match(html, /DecompressionStream is unavailable/);
});

test("buildCompressedLoaderHtml renders fallback content when DecompressionStream is unavailable", () => {
  const html = buildCompressedLoaderHtml({
    gzBase91Safe: "abc123",
    alphabet: "abc123",
  });

  assert.match(html, /renderFallback\(\);return;/);
  assert.match(html, /document\.write\(fallback\)/);
  assert.match(html, /DecompressionStream is unavailable/);
  assert.doesNotMatch(html, /DecompressionStream"\)in window\)\)return/);
});
