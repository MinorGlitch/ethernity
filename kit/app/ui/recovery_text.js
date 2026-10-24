/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */
import { splitFallbackLineLabel } from "../../lib/encoding.js";
import { button } from "./controls.js";

export function recoveryTextField(id, label) {
  return `<div class="field"><label class="label" for="${id}">${label}</label>
    <div class="recovery-editor"><div class="recovery-mirror" aria-hidden="true"><div></div></div>
      <textarea id="${id}" spellcheck="false" autocomplete="off" autocapitalize="off"
        aria-describedby="${id}-guide"></textarea></div>
    <div class="row recovery-entry-tools"><span class="hint" id="${id}-guide" hidden></span>
      ${button(`${id}-tidy`, "Tidy", "ghost")}</div></div>`;
}

function span(text, className = "") {
  const node = document.createElement("span");
  node.className = className;
  node.textContent = text;
  return node;
}

function highlightedLine(line, number) {
  const row = document.createElement("div");
  row.className = "recovery-line";
  const content = span("", "recovery-line-text");
  const [label, body] = splitFallbackLineLabel(line);
  if (label) content.append(span(label, "recovery-label"));
  const header =
    /^[=:\-\s]*(?:main frame|auth frame|key frame|shard frame|shard payload)[=:\-\s]*$/i.test(body);
  let group = 0;
  for (const token of body.split(/([\s-]+)/)) {
    if (!token) continue;
    const separator = /^[\s-]+$/.test(token);
    const word = span(token, !header && !separator && group++ % 2 === 0 ? "recovery-group" : "");
    const invalid = label ? /[^ybndrfg8ejkmcpqxot1uwisza345h769]/i : /[^a-z0-9+/]/i;
    if (!header && !separator && invalid.test(token)) word.classList.add("recovery-invalid");
    content.append(word);
  }
  if (!line) content.textContent = " ";
  row.append(span(String(number), "recovery-line-number"), content);
  return row;
}

export function createRecoveryEditor(input) {
  const editor = input.parentElement;
  const mirror = editor.querySelector(".recovery-mirror");
  const lines = mirror.firstElementChild;
  const guide = editor.parentElement.querySelector(".hint");
  let previous;
  function syncScroll() {
    mirror.style.width = `${input.clientWidth}px`;
    lines.style.transform = `translateY(${-input.scrollTop}px)`;
  }
  input.onscroll = syncScroll;
  const resize = new ResizeObserver(syncScroll);
  resize.observe(input);
  return {
    update(value) {
      if (input.value !== value) input.value = value;
      value = input.value;
      if (value === previous) return;
      previous = value;
      const sourceLines = value.split("\n");
      // Large inputs still use the native editor and full decoder limits. Avoid
      // creating thousands of decoration nodes for each keystroke.
      const plain = value.length > 50_000 || sourceLines.length > 1000;
      editor.classList.toggle("recovery-plain", plain);
      guide.textContent = plain ? "Highlighting paused for large input." : "";
      guide.hidden = !plain;
      lines.replaceChildren(
        ...(plain ? [] : sourceLines.map((line, index) => highlightedLine(line, index + 1))),
      );
      syncScroll();
    },
    dispose() {
      resize.disconnect();
    },
  };
}
