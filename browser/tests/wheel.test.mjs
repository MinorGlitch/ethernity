import assert from "node:assert/strict";
import test from "node:test";
import { wheelInput } from "../src/wheel.js";

function editor() {
  const sent = [];
  const scheduled = new Map();
  const terminal = {
    cols: 80,
    rows: 24,
    modes: { mouseTrackingMode: "any" },
    element: {
      querySelector: () => ({
        getBoundingClientRect: () => ({ left: 10, top: 20, width: 800, height: 480 }),
      }),
    },
  };
  let id = 0;
  const wheel = wheelInput(
    terminal,
    (text) => sent.push(text),
    (cb) => {
      scheduled.set(++id, cb);
      return id;
    },
    (id) => scheduled.delete(id),
  );
  const event = (deltaY, extra = {}) => ({
    deltaX: 0,
    deltaY,
    deltaMode: 0,
    clientX: 55,
    clientY: 125,
    shiftKey: false,
    ctrlKey: false,
    preventDefault() {
      this.prevented = true;
    },
    ...extra,
  });
  const render = () => {
    for (const cb of [...scheduled.values()]) cb();
  };
  return { wheel, sent, event, render, scheduled, terminal };
}

test("keeps pixel distance instead of reducing every gesture to one report", () => {
  const { wheel, sent, event, render, scheduled } = editor();
  for (let i = 0; i < 16; i++) wheel.handle(event(5));
  assert.equal(scheduled.size, 1);
  assert.deepEqual(sent, []);
  render();
  assert.deepEqual(sent, ["\x1b[<65;5;6M".repeat(4)]);
  wheel.handle(event(400));
  render();
  assert.equal(sent[1], "\x1b[<65;5;6M".repeat(20));
});

test("supports line and page units, horizontal wheels and shift scrolling", () => {
  const { wheel, sent, event, render } = editor();
  wheel.handle(event(6, { deltaMode: 1 }));
  render();
  assert.equal(sent[0], "\x1b[<65;5;6M".repeat(6));
  wheel.handle(event(-1, { deltaMode: 2 }));
  render();
  assert.equal(sent[1], "\x1b[<64;5;6M".repeat(24));
  wheel.handle(event(0, { deltaX: 80 }));
  render();
  assert.equal(sent[2], "\x1b[<67;5;6M".repeat(8));
  wheel.handle(event(-80, { shiftKey: true }));
  render();
  assert.equal(sent[3], "\x1b[<66;5;6M".repeat(8));
});

test("direction reversal discards only fractional momentum and preserves report order", () => {
  const { wheel, sent, event, render } = editor();
  wheel.handle(event(65));
  wheel.handle(event(-40));
  render();
  assert.equal(sent[0], "\x1b[<65;5;6M".repeat(3) + "\x1b[<64;5;6M".repeat(2));
});

test("changing targets flushes the old target and does not transfer fractional input", () => {
  const { wheel, sent, event, render } = editor();
  wheel.handle(event(30));
  wheel.handle(event(10, { clientY: 225 }));
  assert.equal(sent[0], "\x1b[<65;5;6M");
  render();
  assert.equal(sent.length, 1);
  wheel.handle(event(10, { clientY: 225 }));
  render();
  assert.equal(sent[1], "\x1b[<65;5;11M");
});

test("flush preserves ordering with keyboard input; disposal cancels pending work", () => {
  const { wheel, sent, event, render, scheduled } = editor();
  wheel.handle(event(80));
  wheel.flush();
  assert.equal(scheduled.size, 0);
  assert.equal(sent[0], "\x1b[<65;5;6M".repeat(4));
  wheel.handle(event(80));
  wheel.dispose();
  render();
  assert.equal(sent.length, 1);
});

test("invalid distances cannot create unbounded input; native mode remains available", () => {
  const { wheel, sent, event, render, terminal } = editor();
  wheel.handle(event(Infinity));
  wheel.handle(event(NaN));
  render();
  assert.equal(sent.length, 0);
  wheel.handle(event(1e10));
  render();
  assert.equal(sent[0], "\x1b[<65;5;6M".repeat(1000));
  terminal.modes.mouseTrackingMode = "none";
  assert.equal(wheel.handle(event(40)), true);
});
