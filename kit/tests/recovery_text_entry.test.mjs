import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { filterZBase32Lines, tidyRecoveryText } from "../lib/encoding.js";
import { parseAutoPayload } from "../app/frames_parse.js";
import { createInitialState } from "../app/state/initial.js";
import { primaryDocumentRecord } from "../app/documents/store.js";
import { FRAME_TYPE_MAIN } from "../app/constants.js";
import { buildFrame, encodeZBase32 } from "./protocol_test_data.mjs";

const cases = JSON.parse(
  readFileSync(new URL("../../tests/fixtures/recovery_text_entry.json", import.meta.url)),
);
test("recovery text cleanup matches the app and is idempotent", () => {
  for (const item of cases) {
    const cleaned = tidyRecoveryText(item.input);
    assert.equal(cleaned, item.expected);
    assert.equal(tidyRecoveryText(cleaned), cleaned);
  }
  for (const invalid of ["01. 02. ybnr", "١. ybnr", "01 ybnr", "01. K"])
    assert.throws(
      () => filterZBase32Lines(tidyRecoveryText(invalid)),
      /outside the z-base-32 alphabet/,
    );
  assert.deepEqual(filterZBase32Lines(tidyRecoveryText("01. 1934 99 ybnr")), ["1934 99 ybnr"]);
});

test("numbered paper text and tidied text recover the same frame", () => {
  const data = Uint8Array.of(19, 34, 99, 1);
  const encoded = encodeZBase32(buildFrame({ frameType: FRAME_TYPE_MAIN, data, total: 1 }));
  const text = encoded
    .match(/.{1,20}/g)
    .map((line, index) => `${index + 1}. \t${line.slice(0, 4)}\u00a0${line.slice(4)}  `)
    .join("\r\n");
  for (const input of [text, tidyRecoveryText(text)]) {
    const state = createInitialState();
    assert.equal(parseAutoPayload(state, input), 1);
    assert.deepEqual(primaryDocumentRecord(state).mainFrames.get(0).data, data);
  }
});
