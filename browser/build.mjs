import { readFile, mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve, basename } from "node:path";
import { build } from "esbuild";

const root = fileURLToPath(new URL(".", import.meta.url));
const output = resolve(root, "../src/ethernity/app/browser/static");
const result = await build({
  absWorkingDir: root,
  entryPoints: ["src/main.js"],
  outfile: resolve(output, "app.js"),
  bundle: true,
  minify: true,
  target: ["chrome100", "firefox102", "safari15"],
  legalComments: "eof",
  write: false,
});
const { dependencies } = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
const license = Buffer.from(
  (
    await Promise.all(
      Object.keys(dependencies).map(
        async (name) =>
          `${name}\n${await readFile(resolve(root, "node_modules", name, "LICENSE"), "utf8")}`,
      ),
    )
  ).join("\n\n"),
);
const files = [...result.outputFiles, { path: resolve(output, "LICENSE.txt"), contents: license }];
if (!process.argv.includes("--check")) await mkdir(output, { recursive: true });
for (const file of files) {
  if (process.argv.includes("--check")) {
    if (!Buffer.from(file.contents).equals(await readFile(file.path))) {
      throw new Error(`${basename(file.path)} is stale. Run npm run build in browser/.`);
    }
  } else {
    await writeFile(file.path, file.contents);
  }
}
