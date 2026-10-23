// Browser sessions use one terminal cell per SGR wheel report.
// Keep fractional trackpad movement and send a frame's reports together.
export function wheelInput(
  terminal,
  send,
  requestFrame = requestAnimationFrame,
  cancelFrame = cancelAnimationFrame,
) {
  let remainderX = 0;
  let remainderY = 0;
  let location = "";
  let pending = "";
  let frame = null;

  function flush() {
    if (frame !== null) cancelFrame(frame);
    frame = null;
    if (pending) send(pending);
    pending = "";
  }

  function reports(delta, remainder, negative, positive, suffix) {
    if (!Number.isFinite(delta)) return remainder;
    if (delta && Math.sign(delta) !== Math.sign(remainder)) remainder = 0;
    const total = remainder + delta;
    const count = Math.trunc(total);
    if (count)
      pending += `\x1b[<${count < 0 ? negative : positive}${suffix}`.repeat(
        Math.min(1000, Math.abs(count)),
      );
    return total - count;
  }

  return {
    handle(event) {
      if (terminal.modes.mouseTrackingMode === "none") return true;
      // A pinch-to-zoom event must not scroll the app.
      if (event.ctrlKey) return false;
      const screen = terminal.element.querySelector(".xterm-screen").getBoundingClientRect();
      if (!screen.width || !screen.height) return false;
      const cellWidth = screen.width / terminal.cols;
      const cellHeight = screen.height / terminal.rows;
      const col = Math.max(
        1,
        Math.min(terminal.cols, Math.floor((event.clientX - screen.left) / cellWidth) + 1),
      );
      const row = Math.max(
        1,
        Math.min(terminal.rows, Math.floor((event.clientY - screen.top) / cellHeight) + 1),
      );
      const suffix = `;${col};${row}M`;
      if (location !== suffix) {
        flush();
        remainderX = remainderY = 0;
        location = suffix;
      }
      let x = event.deltaX;
      let y = event.deltaY;
      if (!Number.isFinite(x) || !Number.isFinite(y)) return false;
      if (event.shiftKey && !x) [x, y] = [y, 0];
      const scaleX =
        event.deltaMode === 1 ? 1 : event.deltaMode === 2 ? terminal.cols : 1 / cellWidth;
      const scaleY =
        event.deltaMode === 1 ? 1 : event.deltaMode === 2 ? terminal.rows : 1 / cellHeight;
      const modifier = event.altKey ? 8 : 0;
      remainderX = reports(x * scaleX, remainderX, 66 + modifier, 67 + modifier, suffix);
      remainderY = reports(y * scaleY, remainderY, 64 + modifier, 65 + modifier, suffix);
      if (pending && frame === null) frame = requestFrame(flush);
      event.preventDefault();
      return false;
    },
    flush,
    dispose() {
      if (frame !== null) cancelFrame(frame);
      frame = null;
      pending = "";
    },
  };
}
