const BLAKE2B_IV = [
    0x6a09e667f3bcc908n,
    0xbb67ae8584caa73bn,
    0x3c6ef372fe94f82bn,
    0xa54ff53a5f1d36f1n,
    0x510e527fade682d1n,
    0x9b05688c2b3e6c1fn,
    0x1f83d9abfb41bd6bn,
    0x5be0cd19137e2179n,
  ];

const BLAKE2B_SIGMA = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
    [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4],
    [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
    [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13],
    [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
    [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11],
    [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
    [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5],
    [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
  ];

const U64_MASK = (1n << 64n) - 1n;

export function blake2b256(input) {
  const outLen = 32;
  const h = BLAKE2B_IV.slice();
  h[0] ^= 0x01010000n | BigInt(outLen);

  const blockBytes = 128;
  let t0 = 0n;
  let t1 = 0n;

  let offset = 0;
  do {
    const blockLen = Math.min(blockBytes, input.length - offset);
    const block = new Uint8Array(blockBytes);
    if (blockLen > 0) block.set(input.slice(offset, offset + blockLen));

    t0 += BigInt(blockLen);
    if (t0 > U64_MASK) {
      t0 &= U64_MASK;
      t1 += 1n;
    }

    const isLast = (offset + blockLen) === input.length;
    blake2bCompress(h, block, t0, t1, isLast);

    offset += blockBytes;
  } while (offset < input.length);

  const out = new Uint8Array(outLen);
  for (let i = 0; i < 4; i++) writeU64LE(out, i * 8, h[i]);
  return out;
}


function blake2bCompress(h, block, t0, t1, isLast) {
    const v = new Array(16);
    for (let i = 0; i < 8; i += 1) {
      v[i] = h[i];
      v[i + 8] = BLAKE2B_IV[i];
    }
    v[12] ^= t0;
    v[13] ^= t1;
    if (isLast) {
      v[14] ^= U64_MASK;
    }
    const m = new Array(16);
    for (let i = 0; i < 16; i += 1) {
      m[i] = readU64LE(block, i * 8);
    }
    for (let r = 0; r < 12; r += 1) {
      const s = BLAKE2B_SIGMA[r];
      blakeG(v, 0, 4, 8, 12, m[s[0]], m[s[1]]);
      blakeG(v, 1, 5, 9, 13, m[s[2]], m[s[3]]);
      blakeG(v, 2, 6, 10, 14, m[s[4]], m[s[5]]);
      blakeG(v, 3, 7, 11, 15, m[s[6]], m[s[7]]);
      blakeG(v, 0, 5, 10, 15, m[s[8]], m[s[9]]);
      blakeG(v, 1, 6, 11, 12, m[s[10]], m[s[11]]);
      blakeG(v, 2, 7, 8, 13, m[s[12]], m[s[13]]);
      blakeG(v, 3, 4, 9, 14, m[s[14]], m[s[15]]);
    }
    for (let i = 0; i < 8; i += 1) {
      h[i] = (h[i] ^ v[i] ^ v[i + 8]) & U64_MASK;
    }
  }

function blakeG(v, a, b, c, d, x, y) {
    v[a] = (v[a] + v[b] + x) & U64_MASK;
    v[d] = rotr64(v[d] ^ v[a], 32n);
    v[c] = (v[c] + v[d]) & U64_MASK;
    v[b] = rotr64(v[b] ^ v[c], 24n);
    v[a] = (v[a] + v[b] + y) & U64_MASK;
    v[d] = rotr64(v[d] ^ v[a], 16n);
    v[c] = (v[c] + v[d]) & U64_MASK;
    v[b] = rotr64(v[b] ^ v[c], 63n);
  }

function rotr64(value, shift) {
    return ((value >> shift) | (value << (64n - shift))) & U64_MASK;
  }

function readU64LE(bytes, offset) {
    let value = 0n;
    for (let i = 0; i < 8; i += 1) {
      value |= BigInt(bytes[offset + i]) << (8n * BigInt(i));
    }
    return value;
  }

function writeU64LE(bytes, offset, value) {
    let v = value;
    for (let i = 0; i < 8; i += 1) {
      bytes[offset + i] = Number(v & 0xffn);
      v >>= 8n;
    }
  }
