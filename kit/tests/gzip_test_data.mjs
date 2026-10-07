import { constants, gzipSync } from "node:zlib";
import { crc32 } from "../lib/crc32.js";

// Shared by the Node tests and browser smoke so native decoders face the same inputs.
export function gzipCases() {
  const data = new TextEncoder().encode("gzip recovery data ".repeat(32));
  const gzip = Uint8Array.from(gzipSync(data));
  const cases = [];
  const add = (name, bytes, expectedLen = data.length, error = null, expected = data) => {
    cases.push({
      name,
      bytes: Array.from(bytes),
      expectedLen,
      error,
      expected: error ? null : Array.from(expected),
    });
  };
  const corrupt = (name, offset, value) => {
    const bytes = gzip.slice();
    bytes[offset] = value;
    add(name, bytes, data.length, "invalid gzip chunk");
  };
  for (const [name, options] of [
    ["stored blocks", { level: 0 }],
    ["fixed Huffman blocks", { strategy: constants.Z_FIXED }],
    ["default compression", {}],
  ]) {
    add(name, gzipSync(data, options));
  }
  // This distribution produces a dynamic Huffman block with zlib.
  const dynamicData = Uint8Array.from({ length: 8192 }, (_, i) => (i * i) % 251);
  const dynamic = gzipSync(dynamicData);
  if (((dynamic[10] >> 1) & 3) !== 2) throw new Error("Expected a dynamic Huffman fixture");
  add("dynamic Huffman blocks", dynamic, dynamicData.length, null, dynamicData);
  add("empty payload", gzipSync(new Uint8Array()), 0, null, new Uint8Array());

  const header = Uint8Array.from([
    ...gzip.subarray(0, 10),
    3,
    0,
    1,
    2,
    3, // FEXTRA: length and contents
    97,
    0, // FNAME
    98,
    0, // FCOMMENT
  ]);
  header[3] = 4 | 8 | 16 | 2;
  const checksum = crc32(header);
  const optional = Uint8Array.from([
    ...header,
    checksum & 255,
    (checksum >>> 8) & 255,
    ...gzip.subarray(10),
  ]);
  add("optional header fields and FHCRC", optional);
  optional[header.length] ^= 1;
  add("invalid header checksum", optional, data.length, "invalid gzip chunk");

  for (const [name, suffix] of [
    ["trailing zero", [0]],
    ["trailing junk", [1, 2, 3]],
    ["second empty member", gzipSync(new Uint8Array())],
    ["second nonempty member", gzip],
  ]) {
    add(name, [...gzip, ...suffix], data.length, "invalid gzip chunk");
  }
  // Even a matching combined output length must not allow a second member.
  add(
    "concatenated members with matching length",
    [...gzip, ...gzip],
    data.length * 2,
    "invalid gzip chunk",
  );
  for (const end of [0, 9, 10, gzip.length - 9, gzip.length - 1]) {
    add(`truncated at ${end}`, gzip.subarray(0, end), data.length, "invalid gzip chunk");
  }
  corrupt("invalid magic", 0, 0);
  corrupt("unsupported compression method", 2, 9);
  corrupt("reserved flags", 3, 0xe0);
  corrupt("reserved DEFLATE block type", 10, 7);
  corrupt("invalid data checksum", gzip.length - 8, gzip[gzip.length - 8] ^ 1);
  corrupt("invalid trailer size", gzip.length - 4, gzip[gzip.length - 4] ^ 1);
  add("output exceeds limit", gzip, data.length - 1, "decoded chunk exceeds raw_len");
  add(
    "output shorter than declared",
    gzip,
    data.length + 1,
    "decoded chunk length does not match raw_len",
  );
  add(
    "streaming output exceeds limit",
    gzipSync(new Uint8Array(256 * 1024)),
    1024,
    "decoded chunk exceeds raw_len",
  );
  return cases;
}
