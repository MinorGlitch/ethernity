/*
 * Copyright (C) 2026 Alex Stoyanov
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License along with this program.
 * If not, see <https://www.gnu.org/licenses/>.
 */

const SHARD_BLOCK_SIZE = 16;
const GF128_POLY = (1n << 128n) | 0x87n;
const GF128_MASK = (1n << 128n) - 1n;

function bigIntFromBytes(bytes) {
    let value = 0n;
    for (const byte of bytes) {
      value = (value << 8n) | BigInt(byte);
    }
    return value;
  }

function bigIntToBytes(value, length) {
    const out = new Uint8Array(length);
    let v = value;
    for (let i = length - 1; i >= 0; i -= 1) {
      out[i] = Number(v & 0xffn);
      v >>= 8n;
    }
    return out;
  }

function gf2Mul(a, b) {
    let f1 = a;
    let f2 = b;
    if (f2 > f1) {
      const tmp = f1;
      f1 = f2;
      f2 = tmp;
    }
    let z = 0n;
    while (f2 > 0n) {
      if (f2 & 1n) {
        z ^= f1;
      }
      f1 <<= 1n;
      f2 >>= 1n;
    }
    return z;
  }

function gf2Deg(value) {
    let v = value;
    let deg = -1;
    while (v > 0n) {
      v >>= 1n;
      deg += 1;
    }
    return deg;
  }

function gf2Div(a, b) {
    if (a < b) {
      return { q: 0n, r: a };
    }
    let q = 0n;
    let r = a;
    const d = gf2Deg(b);
    while (gf2Deg(r) >= d) {
      const shift = BigInt(gf2Deg(r) - d);
      const s = 1n << shift;
      q ^= s;
      r ^= gf2Mul(b, s);
    }
    return { q, r };
  }

function gf128Mul(a, b) {
    let x = a & GF128_MASK;
    let y = b & GF128_MASK;
    let z = 0n;
    while (y > 0n) {
      if (y & 1n) {
        z ^= x;
      }
      y >>= 1n;
      x <<= 1n;
      if (x & (1n << 128n)) {
        x ^= GF128_POLY;
      }
    }
    return z & GF128_MASK;
  }

function gf128Inverse(a) {
    if (a === 0n) {
      throw new Error("inversion of zero");
    }
    let r0 = a;
    let r1 = GF128_POLY;
    let s0 = 1n;
    let s1 = 0n;
    while (r1 > 0n) {
      const { q } = gf2Div(r0, r1);
      const r2 = r0 ^ gf2Mul(q, r1);
      const s2 = s0 ^ gf2Mul(q, s1);
      r0 = r1;
      r1 = r2;
      s0 = s1;
      s1 = s2;
    }
    return s0 & GF128_MASK;
  }

function gf128Div(a, b) {
    if (a === 0n) return 0n;
    return gf128Mul(a, gf128Inverse(b));
  }

function shamirCombine128(pairs) {
    let result = 0n;
    for (let j = 0; j < pairs.length; j += 1) {
      const xj = pairs[j].x;
      const yj = pairs[j].y;
      let numerator = 1n;
      let denominator = 1n;
      for (let m = 0; m < pairs.length; m += 1) {
        if (m === j) continue;
        const xm = pairs[m].x;
        numerator = gf128Mul(numerator, xm);
        denominator = gf128Mul(denominator, xj ^ xm);
      }
      const term = gf128Mul(yj, gf128Div(numerator, denominator));
      result ^= term;
    }
    return result & GF128_MASK;
  }

export function recoverSecretFromShards(shares) {
    if (!shares.length) {
      throw new Error("no shard payloads provided");
    }
    const threshold = shares[0].threshold;
    const shareTotal = shares[0].shareCount;
    const keyType = shares[0].keyType;
    const secretLen = shares[0].secretLen;
    const seen = new Set();

    for (const share of shares) {
      if (share.keyType !== keyType) {
        throw new Error("shard key types do not match");
      }
      if (share.threshold !== threshold) {
        throw new Error("shard thresholds do not match");
      }
      if (share.shareCount !== shareTotal) {
        throw new Error("shard share counts do not match");
      }
      if (seen.has(share.shareIndex)) {
        throw new Error("duplicate shard index");
      }
      seen.add(share.shareIndex);
      if (share.shareIndex <= 0 || share.shareIndex > 255) {
        throw new Error("shard index out of range");
      }
      if (share.secretLen !== secretLen) {
        throw new Error("shard secret lengths do not match");
      }
      if (share.share.length % SHARD_BLOCK_SIZE !== 0) {
        throw new Error("shard share length must be a multiple of block size");
      }
    }

    if (shares.length < threshold) {
      throw new Error(`need at least ${threshold} shard(s) to recover secret`);
    }

    const blockCount = Math.ceil(secretLen / SHARD_BLOCK_SIZE);
    const expectedLen = blockCount * SHARD_BLOCK_SIZE;
    for (const share of shares) {
      if (share.share.length !== expectedLen) {
        throw new Error("shard share length does not match secret length");
      }
    }

    const orderedShares = shares.slice().sort((a, b) => a.shareIndex - b.shareIndex);
    const useShares = orderedShares.slice(0, threshold);

    const secretBytes = new Uint8Array(blockCount * SHARD_BLOCK_SIZE);
    let offset = 0;
    for (let blockIdx = 0; blockIdx < blockCount; blockIdx += 1) {
      const start = blockIdx * SHARD_BLOCK_SIZE;
      const end = start + SHARD_BLOCK_SIZE;
      const pairs = useShares.map(share => ({
        x: BigInt(share.shareIndex),
        y: bigIntFromBytes(share.share.slice(start, end)),
      }));
      const blockValue = shamirCombine128(pairs);
      const blockBytes = bigIntToBytes(blockValue, SHARD_BLOCK_SIZE);
      secretBytes.set(blockBytes, offset);
      offset += blockBytes.length;
    }
    return secretBytes.slice(0, secretLen);
  }
