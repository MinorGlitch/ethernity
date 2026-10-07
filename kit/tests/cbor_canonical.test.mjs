/* Copyright (C) 2026 Alex Stoyanov. SPDX-License-Identifier: GPL-3.0-or-later */

import assert from "node:assert/strict";
import test from "node:test";
import { decodeCbor, decodeDeterministicCbor, encodeCbor } from "../lib/cbor.js";

const bytes = (hex) => Uint8Array.from(Buffer.from(hex.replaceAll(" ", ""), "hex"));
const decode = (hex, options) => decodeDeterministicCbor(bytes(hex), "probe", options);

test("canonical CBOR validates integer and length widths inside nested values", () => {
  for (const hex of [
    "1817", // 23 in two bytes
    "1900ff", // 255 in three bytes
    "1a0000ffff", // 65535 in five bytes
    "1b00000000ffffffff", // 32-bit value in nine bytes
    "3817", // negative integer with an overlong argument
    "5800", // empty bytes with an overlong length
    "7800", // empty text with an overlong length
    "9800", // empty array with an overlong length
    "b800", // empty map with an overlong length
    "a16161811801", // overlong integer inside a nested array
  ]) {
    assert.throws(() => decode(hex), /deterministic CBOR/, hex);
  }
  for (const [hex, expected] of [
    ["17", 23],
    ["1818", 24],
    ["18ff", 255],
    ["190100", 256],
    ["19ffff", 65535],
    ["1a00010000", 65536],
    ["1affffffff", 4294967295],
    ["1b0000000100000000", 4294967296],
    ["1b001fffffffffffff", Number.MAX_SAFE_INTEGER],
    ["3b001fffffffffffff", -9007199254740992],
  ]) {
    assert.equal(decode(hex), expected, hex);
  }
  assert.throws(() => decode("1b0020000000000000"), /integer too large/);
  assert.throws(() => decode("3b0020000000000000"), /integer too large/);
  assert.equal(decodeCbor(bytes("1801")), 1);
  assert.throws(() => decodeDeterministicCbor(bytes("1801")), /deterministic CBOR/);
});

test("canonical maps enforce length-first order and reject repeated wire keys", () => {
  const options = { preserveMapType: true };
  assert.deepEqual(
    decode("a22000181800", options),
    new Map([
      [-1, 0],
      [24, 0],
    ]),
  );
  assert.deepEqual(decode("a261620062616100"), { b: 0, aa: 0 });
  for (const hex of [
    "a21818002000", // bytewise order differs from length-first order
    "a2616200616100", // same-length keys reversed
    "a201000101", // repeated integer key
    "a2616100616101", // repeated text key
    "a2410100410101", // repeated byte-string key
    "a16161a201000101", // duplicate in a nested map
  ]) {
    assert.throws(() => decode(hex, options), /deterministic CBOR/, hex);
  }
  assert.throws(() => decode("a10100"), /deterministic CBOR/);
  assert.throws(() => decode("a1695f5f70726f746f5f5ff6"), /deterministic CBOR/);
});

test("canonical text keeps UTF-8 validation and binary fields remain independent copies", () => {
  assert.equal(decode("65c3a9e6b0b4"), "\u00e9\u6c34");
  for (const hex of ["61ff", "62c080", "63eda080", "61c2", "63efbbbf"]) {
    assert.throws(() => decode(hex), /deterministic CBOR/, hex);
  }
  const input = bytes("43010203");
  const decoded = decodeDeterministicCbor(input, "probe");
  input[1] = 99;
  assert.deepEqual(decoded, Uint8Array.of(1, 2, 3));
});

test("every finite half float roundtrips with its wire type and rejects wider encodings", () => {
  const wide = new Uint8Array(9);
  wide[0] = 0xfb;
  const view = new DataView(wide.buffer);
  for (let bits = 0; bits <= 0xffff; bits += 1) {
    if ((bits & 0x7c00) === 0x7c00) continue;
    const encoded = Uint8Array.of(0xf9, bits >> 8, bits & 0xff);
    const value = decodeDeterministicCbor(encoded, "probe", { preserveFloatType: true });
    assert.deepEqual(encodeCbor(value), encoded);
    const number = decodeCbor(encoded);
    view.setFloat64(1, number);
    assert.throws(() => decodeDeterministicCbor(wide, "probe"), /deterministic CBOR/);
  }
  assert.ok(Object.is(decode("f98000"), -0));
  assert.equal(Number.isInteger(decode("f93c00", { preserveFloatType: true })), false);
});

test("single and double precision retain values and use the shortest exact float width", () => {
  for (const [hex, expected] of [
    ["fa3f8ccccd", Math.fround(1.1)],
    ["fb3ff199999999999a", 1.1],
    ["fa00000001", 2 ** -149],
    ["fb0000000000000001", Number.MIN_VALUE],
    ["fa47800000", 65536],
    ["fb7fefffffffffffff", Number.MAX_VALUE],
  ]) {
    assert.equal(decode(hex), expected, hex);
    assert.deepEqual(encodeCbor(decode(hex, { preserveFloatType: true })), bytes(hex));
  }
  for (const hex of ["fa3fc00000", "fb3ff19999a0000000", "fa80000000", "fb8000000000000000"]) {
    assert.throws(() => decode(hex), /deterministic CBOR/, hex);
  }
});

test("CBOR rejects truncated items, trailing data, indefinite lengths and unsupported types", () => {
  for (const hex of [
    "",
    "18",
    "1900",
    "1a000000",
    "1b00000000000000",
    "4200",
    "6200",
    "81",
    "a16161",
    "f900",
    "fa000000",
    "fb00000000000000",
  ]) {
    assert.throws(() => decode(hex), /truncated/, hex);
  }
  assert.throws(() => decode("0000"), /extra CBOR data/);
  for (const hex of ["5f", "7f", "9f", "bf"]) {
    assert.throws(() => decode(hex), /indefinite CBOR lengths/, hex);
  }
  assert.throws(() => decode("c000"), /unsupported CBOR type/);
  assert.throws(() => decode("f800"), /unsupported CBOR simple value/);
});
