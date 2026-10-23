import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { Unicode11Addon } from "@xterm/addon-unicode11";
import { ClipboardAddon } from "@xterm/addon-clipboard";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import { wheelInput } from "./wheel.js";

const element = document.getElementById("terminal");
const terminal = new Terminal({
  allowProposedApi: true,
  fontSize: Number(element.dataset.fontSize),
  fontFamily: "Monaco, 'Courier New', monospace",
  scrollback: 0,
});
const fit = new FitAddon();
terminal.loadAddon(fit);
terminal.loadAddon(new Unicode11Addon());
terminal.unicode.activeVersion = "11";
terminal.loadAddon(new ClipboardAddon());
terminal.loadAddon(new WebLinksAddon());
terminal.open(element);
fit.fit();

const address = new URL(element.dataset.sessionWebsocketUrl, location.href);
address.searchParams.set("width", terminal.cols);
address.searchParams.set("height", terminal.rows);
const socket = new WebSocket(address);
socket.binaryType = "arraybuffer";
function send(type, value) {
  if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify([type, value]));
}
const wheel = wheelInput(terminal, (data) => send("stdin", data));
terminal.attachCustomWheelEventHandler(wheel.handle);
terminal.onData((data) => {
  wheel.flush();
  send("stdin", data);
});
terminal.onResize(({ cols, rows }) => {
  wheel.flush();
  send("resize", { width: cols, height: rows });
});
terminal.textarea.addEventListener("focus", () => send("focus"));
terminal.textarea.addEventListener("blur", () => send("blur"));
const resize = new ResizeObserver(() => fit.fit());
resize.observe(element);

socket.addEventListener("open", () => {
  fit.fit();
  send("resize", { width: terminal.cols, height: terminal.rows });
  terminal.focus();
  send("focus");
});
socket.addEventListener("message", ({ data }) => {
  if (typeof data !== "string") {
    terminal.write(new Uint8Array(data), () => document.body.classList.add("-first-byte"));
    return;
  }
  const [type, value] = JSON.parse(data);
  if (type === "open_url") window.open(value.url, value.new_tab ? "_blank" : "_self", "noopener");
  if (type === "deliver_file_start")
    window.open(`/download/${encodeURIComponent(value)}`, "_blank", "noopener");
});
socket.addEventListener("close", () => {
  wheel.dispose();
  resize.disconnect();
  document.body.classList.add("-closed");
});
window.addEventListener(
  "pagehide",
  () => {
    wheel.dispose();
    resize.disconnect();
    socket.close();
    terminal.dispose();
  },
  { once: true },
);
