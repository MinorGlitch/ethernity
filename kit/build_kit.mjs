import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const kitDir = resolve(fileURLToPath(new URL(".", import.meta.url)));
const inputPath = resolve(kitDir, process.argv[2] ?? "recovery_kit.html");
const bundleName = process.argv[3] ?? "recovery_kit.bundle.html";
const rawBundleName = bundleName.replace(/\.html$/, ".raw.html");
const rawOutputPath = resolve(kitDir, "dist", rawBundleName);
const outputPath = resolve(kitDir, "dist", bundleName);
const packagePath = resolve(kitDir, "..", "ethernity", "kit", bundleName);
await mkdir(dirname(outputPath), { recursive: true });

const html = await readFile(inputPath, "utf8");
const scriptTagRe = /<script\b[^>]*>[\s\S]*?<\/script>/g;

const tmpBase = resolve(tmpdir(), `ethernity-kit-${Date.now()}`);
const tmpOut = `${tmpBase}.min.js`;
const entryPoint = resolve(kitDir, "app.js");

const esbuildArgs = [
  entryPoint,
  "--bundle",
  "--format=iife",
  "--platform=browser",
  "--target=es2020",
  "--minify",
  "--tree-shaking=true",
  "--legal-comments=none",
  "--define:process.env.NODE_ENV=\"production\"",
  `--outfile=${tmpOut}`,
];
const result = spawnSync("npx", ["esbuild", ...esbuildArgs], {
  stdio: "inherit",
});
if (result.status !== 0) {
  process.exit(result.status ?? 1);
}

const minified = await readFile(tmpOut, "utf8");
const inlined = html
  .replace(scriptTagRe, "")
  .replace("</body>", () => `<script>${minified}</script>\n</body>`);

const tmpHtml = `${tmpBase}.html`;
await writeFile(tmpHtml, inlined, "utf8");

const htmlMinArgs = [
  "--collapse-whitespace",
  "--remove-comments",
  "--remove-redundant-attributes",
  "--remove-script-type-attributes",
  "--remove-style-link-type-attributes",
  "--use-short-doctype",
  "--minify-css",
  "true",
  "-o",
  rawOutputPath,
  tmpHtml,
];
const htmlResult = spawnSync("npx", ["html-minifier-terser", ...htmlMinArgs], {
  stdio: "inherit",
});
if (htmlResult.status !== 0) {
  process.exit(htmlResult.status ?? 1);
}

const rawBundle = await readFile(rawOutputPath, "utf8");
const gzPayload = gzipSync(Buffer.from(rawBundle, "utf8"), { level: 9 });
const gzBase64 = gzPayload.toString("base64");
const loaderHtml = `<!doctype html><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Ethernity Recovery Kit</title><style>body{margin:0;background:#0b1426;color:#f2f6ff;font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,sans-serif;display:grid;place-items:center;min-height:100vh}main{max-width:720px;padding:24px;text-align:center}h1{margin:0 0 12px;font-size:20px}p{margin:0 0 12px;color:#b8c7e2}code{background:#111f36;border:1px solid #2a3b5d;border-radius:8px;padding:2px 6px}</style><main><h1>Loading recovery kit...</h1><p id=\"status\">Decompressing bundle with <code>DecompressionStream</code>.</p></main><script>(async()=>{const p=\"${gzBase64}\";if(!(\"DecompressionStream\"in window)){document.getElementById(\"status\").textContent=\"This kit requires DecompressionStream (gzip). Use a newer browser or a JS fallback.\";return}const b=Uint8Array.from(atob(p),c=>c.charCodeAt(0));const ds=new DecompressionStream(\"gzip\");const s=new Blob([b]).stream().pipeThrough(ds);const t=await new Response(s).text();document.open();document.write(t);document.close();})().catch(e=>{const el=document.getElementById(\"status\");if(el)el.textContent=\"Failed to load bundle: \"+e;});</script>`;

const tmpLoader = `${tmpBase}.loader.html`;
await writeFile(tmpLoader, loaderHtml, "utf8");
const loaderMinArgs = [...htmlMinArgs];
loaderMinArgs[loaderMinArgs.length - 2] = outputPath;
loaderMinArgs[loaderMinArgs.length - 1] = tmpLoader;
const loaderResult = spawnSync("npx", ["html-minifier-terser", ...loaderMinArgs], {
  stdio: "inherit",
});
if (loaderResult.status !== 0) {
  process.exit(loaderResult.status ?? 1);
}

await mkdir(dirname(packagePath), { recursive: true });
await copyFile(outputPath, packagePath);

console.log(`Wrote ${rawOutputPath}`);
console.log(`Wrote ${outputPath}`);
console.log(`Wrote ${packagePath}`);
