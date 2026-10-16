/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */

// Markup helpers accept authored labels only. Recovery data is assigned through
// textContent/value below, never interpolated into HTML.
export function field(
  id,
  label,
  { textarea = false, type = "text", readOnly = false, hint = "" } = {},
) {
  const attrs = `id="${id}" spellcheck="false"${readOnly ? ' readonly class="code"' : ""}${hint ? ` aria-describedby="${id}-hint"` : ""}`;
  return `<div class="field"><label class="label" for="${id}">${label}</label>${
    textarea
      ? `<textarea ${attrs}></textarea>`
      : `<input ${attrs} type="${type}"${type === "password" ? ' autocomplete="off"' : ""}>`
  }${hint ? `<div id="${id}-hint" class="hint">${hint}</div>` : ""}</div>`;
}

export function button(id, label, className = "") {
  return `<button id="${id}" type="button" class="${className}">${label}</button>`;
}

export function statusMarkup(id, { collection = false, fields = "" } = {}) {
  return `<div id="${id}" class="step-section" hidden>
    <div class="status" role="status" aria-live="polite" aria-atomic="true" hidden></div>
    ${collection ? '<div class="diag-list prominent" hidden></div>' : ""}
    <details class="details" hidden><summary>Technical details</summary>
      <div class="diagnostic-text" hidden></div>${fields}
      ${collection ? '<div class="diag-list secondary-diagnostics" hidden></div>' : ""}
    </details></div>`;
}

export function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

export function setValue(node, value) {
  // Avoid resetting the caret or selection when the input already holds this value.
  if (node.value !== value) node.value = value;
}

export function setButton(node, enabled, reason = "", label) {
  node.disabled = !enabled;
  node.title = enabled ? "" : (reason ?? "");
  if (label !== undefined) setText(node, label);
}

export function updateStatus(node, status, items) {
  const message = node.querySelector(".status");
  const hasMessage = Boolean(status.lines.length);
  message.hidden = !hasMessage;
  message.className = `status ${hasMessage ? status.type : ""}`;
  setText(message, status.lines.join("\n"));
  const text = node.querySelector(".diagnostic-text");
  text.hidden = !status.details?.length;
  setText(text, status.details?.join("\n") ?? "");
  node.querySelector("details").hidden = !hasMessage || (!items && text.hidden);
  node.hidden = !hasMessage;
  if (items) {
    updateDiagnostics(
      node.querySelector(".prominent"),
      items.filter((item) => item.prominent),
    );
    updateDiagnostics(
      node.querySelector(".secondary-diagnostics"),
      items.filter((item) => !item.prominent),
    );
  }
}

function updateDiagnostics(node, items) {
  node.hidden = !items.length;
  node.replaceChildren(
    ...items.map((item) => {
      const row = document.createElement("div");
      row.className = `diag-row ${item.tone ?? ""}`;
      const label = document.createElement("div");
      label.className = "diag-label";
      label.textContent = item.label;
      const value = document.createElement("div");
      value.className = "diag-value";
      value.textContent = item.value ?? "-";
      if (item.detail) {
        const hint = document.createElement("div");
        hint.className = "hint";
        hint.textContent = item.detail;
        value.append(hint);
      }
      row.append(label, value);
      return row;
    }),
  );
}
