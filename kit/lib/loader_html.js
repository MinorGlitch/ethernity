/*
 * Copyright (C) 2026 Alex Stoyanov
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along with this program.
 * If not, see <https://www.gnu.org/licenses/>.
 */

const DEFAULT_TITLE = "Ethernity Recovery Kit";
const UNSUPPORTED_MESSAGE =
  "This browser cannot open the compressed recovery kit because DecompressionStream is unavailable.";
const UNSUPPORTED_HINT =
  "Open the kit in a current browser or use the desktop app to continue recovery.";
const SUPPORTED_COMPRESSIONS = new Set(["gzip", "brotli"]);

export function buildUnsupportedLoaderHtml({ title = DEFAULT_TITLE } = {}) {
  return `<!doctype html><meta charset=utf-8><meta name=viewport content=width=device-width,initial-scale=1><title>${title}</title><style>body{font:16px/1.5 system-ui,sans-serif;margin:2rem;max-width:42rem}</style><h1>Recovery kit cannot open here</h1><p>${UNSUPPORTED_MESSAGE}</p><p>${UNSUPPORTED_HINT}</p>`;
}

function normalizeCompression(compression = "gzip") {
  const normalized = String(compression).toLowerCase();
  if (!SUPPORTED_COMPRESSIONS.has(normalized)) {
    throw new Error("compression must be one of: gzip, brotli");
  }
  return normalized;
}

function requireNonEmptyString(value, name) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${name} must be a non-empty string`);
  }
  return value;
}

export function buildCompressedLoaderHtml({
  payloadBase91Safe,
  alphabet,
  compression = "gzip",
  title = DEFAULT_TITLE,
}) {
  const payload = requireNonEmptyString(payloadBase91Safe, "payloadBase91Safe");
  const codecAlphabet = requireNonEmptyString(alphabet, "alphabet");
  const format = normalizeCompression(compression);
  const fallbackHtml = buildUnsupportedLoaderHtml({ title });
  return `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="ethernity-kit-compression" content=${JSON.stringify(format)}><title>${title}</title><script>(async()=>{const p=${JSON.stringify(payload)},a=${JSON.stringify(codecAlphabet)},f=${JSON.stringify(format)},h=${JSON.stringify(fallbackHtml)},w=t=>{document.open();document.write(t);document.close()},d=t=>{let b=0,n=0,v=-1,o=[];for(let i=0,c;i<t.length;i++){c=a.indexOf(t[i]);if(c<0)continue;if(v<0){v=c;continue}v+=c*91;b|=v<<n;n+=(v&8191)>88?13:14;for(;n>7;n-=8,b>>=8)o.push(b&255);v=-1}return v<0?new Uint8Array(o):(o.push((b|v<<n)&255),new Uint8Array(o))};try{if(typeof DecompressionStream!="function")throw 0;w(await new Response(new Blob([d(p)]).stream().pipeThrough(new DecompressionStream(f))).text())}catch{w(h)}})();</script>`;
}
