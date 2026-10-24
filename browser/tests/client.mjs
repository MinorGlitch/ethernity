import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { EventEmitter, once } from "node:events";
import { chromium, firefox, webkit } from "playwright";

const resources = new URL("../../src/ethernity/app/browser/", import.meta.url);
const server = createServer(async (req, res) => {
  if (req.url === "/") {
    const html = (await readFile(new URL("app_index.html", resources), "utf8"))
      .replaceAll("{{ config.static.url }}", "/static/")
      .replaceAll("{{ app_websocket_url }}", `ws://127.0.0.1:${server.address().port}/ws`)
      .replaceAll("{{ font_size }}", "16");
    res.setHeader("Content-Type", "text/html");
    res.end(html);
  } else if (["/static/app.js", "/static/app.css"].includes(req.url)) {
    res.setHeader("Content-Type", req.url.endsWith("js") ? "text/javascript" : "text/css");
    res.end(await readFile(new URL(req.url.slice(1), resources)));
  } else {
    res.writeHead(404);
    res.end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const engines = { chromium, firefox, webkit };
try {
  for (const name of process.argv.slice(2).length
    ? process.argv.slice(2)
    : ["chromium", "webkit"]) {
    const browser = await engines[name].launch({ headless: true });
    try {
      const page = await browser.newPage({ viewport: { width: 1000, height: 700 } });
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const messages = [];
      const received = new EventEmitter();
      let route;
      let closed = false;
      let ready = false;
      await page.routeWebSocket(/\/ws\?/, (ws) => {
        route = ws;
        ws.onClose(() => {
          closed = true;
        });
        ws.onMessage((raw) => {
          const message = JSON.parse(raw);
          messages.push(message);
          received.emit("message");
          if (!ready && message[0] === "resize") {
            ready = true;
            ws.send(
              Buffer.from("\x1b[?1049h\x1b[?1003h\x1b[?1006h\x1b[?2004h\x1b[HScrolling test\r\n"),
            );
          }
        });
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.locator("body.-first-byte").waitFor();
      assert.ok(messages.some(([type]) => type === "focus"));
      const size = messages.find(([type]) => type === "resize")[1];
      assert.ok(size.width > 40 && size.height > 20);
      const screen = page.locator(".xterm-screen");
      const bounds = await screen.boundingBox();
      const rowHeight = bounds.height / size.height;
      const wheelCount = () =>
        messages
          .filter(([type]) => type === "stdin")
          .flatMap(([, data]) => data.split("\x1b").filter((part) => /^\[<6[45];/.test(part)))
          .length;
      const before = wheelCount();
      await screen.dispatchEvent("wheel", {
        deltaY: rowHeight * 20,
        deltaMode: 0,
        clientX: bounds.x + 100,
        clientY: bounds.y + 100,
        bubbles: true,
        cancelable: true,
      });
      await page.evaluate(
        () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
      );
      assert.equal(
        wheelCount() - before,
        20,
        "A 20-row gesture must not collapse to one scroll report",
      );
      const count = wheelCount();
      for (let i = 0; i < 8; i++)
        await screen.dispatchEvent("wheel", {
          deltaY: rowHeight / 2,
          deltaMode: 0,
          clientX: bounds.x + 100,
          clientY: bounds.y + 100,
          bubbles: true,
          cancelable: true,
        });
      await page.evaluate(
        () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
      );
      assert.equal(wheelCount() - count, 4, "Small trackpad movements must accumulate");
      const inputs = () =>
        messages
          .filter(([type]) => type === "stdin")
          .map(([, data]) => data)
          .join("");
      async function expectInput(text) {
        const signal = AbortSignal.timeout(5000);
        try {
          while (!inputs().includes(text)) await once(received, "message", { signal });
        } catch (error) {
          throw new Error(`Missing input ${JSON.stringify(text)} in ${JSON.stringify(inputs())}`, {
            cause: error,
          });
        }
      }
      await page.mouse.click(bounds.x + 100, bounds.y + 100);
      await expectInput("\x1b[<0;");
      await page.keyboard.type("abc");
      await expectInput("abc");
      await page.locator(".xterm-helper-textarea").evaluate((textarea) => {
        const event = new Event("paste", { bubbles: true, cancelable: true });
        // Firefox strips data from untrusted ClipboardEvents. Supply the clipboard boundary.
        Object.defineProperty(event, "clipboardData", {
          value: { getData: () => "first line\nsecond line" },
        });
        textarea.dispatchEvent(event);
      });
      await expectInput("\x1b[200~first line\rsecond line\x1b[201~");
      await page.evaluate(() => {
        window.opened = [];
        window.open = (...args) => window.opened.push(args);
      });
      route.send(JSON.stringify(["open_url", { url: "/example", new_tab: true }]));
      route.send(JSON.stringify(["deliver_file_start", "file-key"]));
      await page.waitForFunction(() => window.opened.length === 2);
      assert.deepEqual(await page.evaluate(() => window.opened), [
        ["/example", "_blank", "noopener"],
        ["/download/file-key", "_blank", "noopener"],
      ]);
      await page.setViewportSize({ width: 800, height: 500 });
      await page.evaluate(
        () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
      );
      const resized = messages.filter(([type]) => type === "resize").at(-1)[1];
      assert.ok(resized.width < size.width && resized.height < size.height);
      await route.close();
      await page.locator("body.-closed").waitFor();
      assert.deepEqual(errors, []);
      await page.close();
      assert.ok(closed);
      console.log(`${name}: distance, trackpad, typing, resize, disconnect passed`);
    } finally {
      await browser.close();
    }
  }
} finally {
  await new Promise((resolve) => server.close(resolve));
}
