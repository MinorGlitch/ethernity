/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */

// This function is bundled on its own into the printed startup QR. Keep its dependencies
// inside the function so that the recovery app and scanner never enter the startup page.
export function mountKitAssembler(config) {
  const [kitId, total, encodedSize, compression] = config;
  const parts = [];
  let collectedSize = 0;
  const byId = (id) => document.getElementById(id);
  const input = byId("scans");
  const status = byId("status");
  const notice = byId("notice");
  const save = byId("save");
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ$%*+-./:";
  const header = /^EK1:([0-9A-F]{12}):([0-9A-F]{4}):([0-9A-F]{4}):([0-9A-F]{4}):([0-9A-F]{8}):/;

  function checksum(text) {
    let crc = -1;
    for (const char of text) {
      crc ^= char.charCodeAt(0);
      for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (-(crc & 1) & 0xedb88320);
    }
    return (crc ^ -1) >>> 0;
  }

  function refresh() {
    const missing = [];
    for (let index = 3; index <= total; index++)
      if (parts[index] === undefined) missing.push(index);
    status.textContent = `${parts.filter(Boolean).length} of ${total - 2} parts collected. ${missing.length ? `Missing QR: ${missing.join(", ")}` : "Ready to save."}`;
    save.disabled = missing.length > 0;
  }

  function add(text) {
    notice.textContent = "";
    try {
      let remaining = text.replace(/\s/g, "");
      if (!remaining) throw Error("Paste a scan first.");
      while (remaining) {
        const match = remaining.match(header);
        if (!match) throw Error("Invalid scan. Copy all text.");
        const [, id, indexHex, totalHex, lengthHex, crcHex] = match;
        const index = Number.parseInt(indexHex, 16);
        const length = Number.parseInt(lengthHex, 16);
        if (id !== kitId || Number.parseInt(totalHex, 16) !== total)
          throw Error("This fragment belongs to another kit.");
        const data = remaining.slice(match[0].length, match[0].length + length);
        if (
          index < 3 ||
          index > total ||
          !length ||
          data.length !== length ||
          [...data].some((char) => !alphabet.includes(char)) ||
          checksum(match[0].slice(0, -9) + data) !== Number.parseInt(crcHex, 16)
        )
          throw Error(`Damaged QR ${index}. Scan it again.`);
        if (parts[index] !== undefined && parts[index] !== data)
          throw Error(`Conflicting QR ${index}. Existing part kept.`);
        if (parts[index] === undefined) {
          if (collectedSize + length > encodedSize) throw Error("Kit data is too long.");
          collectedSize += length;
          parts[index] = data;
        }
        remaining = remaining.slice(match[0].length + length);
      }
      input.value = "";
    } catch (error) {
      notice.textContent = error.message;
    }
    refresh();
  }

  byId("add").onclick = () => add(input.value);
  byId("file").onchange = async (event) => {
    try {
      const texts = [];
      for (const file of event.target.files) texts.push(await file.text());
      add(texts.join("\n"));
    } catch {
      notice.textContent = "Could not read this text file.";
    }
    event.target.value = "";
  };
  save.onclick = async () => {
    if (save.disabled) return;
    save.disabled = true;
    notice.textContent = "Checking kit...";
    try {
      const text = Array.from({ length: total - 2 }, (_, i) => parts[i + 3]).join("");
      if (text.length !== encodedSize) throw Error("Wrong kit length.");
      // Each 15-byte block uses 22 digits. The final block has one exact digit
      // count for its byte length; BigInt preserves all 120 bits, including zeros.
      const digitCounts = [0, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18, 20, 21, 22];
      const tailBytes = digitCounts.indexOf(text.length % 22);
      if (tailBytes < 0) throw Error("Invalid kit data.");
      const bytes = new Uint8Array(Math.floor(text.length / 22) * 15 + tailBytes);
      let offset = 0;
      for (let i = 0; i < text.length; i += 22) {
        const length = Math.min(22, text.length - i);
        const count = digitCounts.indexOf(length);
        let value = 0n;
        for (let j = length - 1; j >= 0; j--)
          value = value * 44n + BigInt(alphabet.indexOf(text[i + j]));
        for (let j = count - 1; j >= 0; j--) {
          bytes[offset + j] = Number(value & 255n);
          value >>= 8n;
        }
        if (value !== 0n) throw Error("Invalid kit data.");
        offset += count;
      }
      const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream(compression));
      const reader = stream.getReader();
      const chunks = [];
      let size = 0;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.length;
          if (size > 1000000) throw Error("Kit is too large.");
          chunks.push(value);
        }
      } catch (error) {
        await reader.cancel().catch(() => {});
        throw error;
      } finally {
        reader.releaseLock();
      }
      const html = await new Blob(chunks).text();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      link.download = "recovery_kit.bundle.html";
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 60000);
      notice.textContent = "Saved. Open the downloaded HTML.";
    } catch {
      notice.textContent = "Could not rebuild the kit. Check your scans and browser support.";
    }
    refresh();
  };
  refresh();
}
