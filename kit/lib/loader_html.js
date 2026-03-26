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

export function buildUnsupportedLoaderHtml({ title = DEFAULT_TITLE } = {}) {
  return `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title><style>body{margin:0;font:16px/1.5 ui-sans-serif,system-ui,sans-serif;background:#f5f1e8;color:#231f19}main{max-width:42rem;margin:0 auto;padding:4rem 1.5rem}h1{margin:0 0 1rem;font-size:2rem;line-height:1.1}p{margin:0 0 1rem}.panel{padding:1.25rem 1.5rem;border:1px solid #c8bca6;border-radius:1rem;background:#fffaf1;box-shadow:0 0.75rem 2rem rgba(35,31,25,.08)}</style><main><div class="panel"><h1>Recovery kit cannot open here</h1><p>${UNSUPPORTED_MESSAGE}</p><p>${UNSUPPORTED_HINT}</p></div></main>`;
}

export function buildCompressedLoaderHtml({ gzBase91Safe, alphabet, title = DEFAULT_TITLE }) {
  const fallbackHtml = buildUnsupportedLoaderHtml({ title });
  return `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title><script>(async()=>{const p=${JSON.stringify(gzBase91Safe)};const a=${JSON.stringify(alphabet)};const fallback=${JSON.stringify(fallbackHtml)};const renderFallback=()=>{document.open();document.write(fallback);document.close();};const decode=t=>{let b=0,n=0,v=-1,o=[];for(let i=0;i<t.length;i++){const c=a.indexOf(t[i]);if(c===-1)continue;if(v<0){v=c;continue}v+=c*91;b|=v<<n;n+=(v&8191)>88?13:14;while(n>7){o.push(b&255);b>>=8;n-=8}v=-1}if(v>=0)o.push((b|v<<n)&255);return new Uint8Array(o)};if(!("DecompressionStream" in window)){renderFallback();return;}try{const b=decode(p);const ds=new DecompressionStream("gzip");const s=new Blob([b]).stream().pipeThrough(ds);const t=await new Response(s).text();document.open();document.write(t);document.close();}catch{renderFallback();}})();</script>`;
}
