const textDecoder = new TextDecoder();
const textEncoder = new TextEncoder();

export function decodeCbor(bytes) {
  const result = decodeCborItem(bytes, 0);
  if (result.offset !== bytes.length) {
    throw new Error("extra CBOR data");
  }
  return result.value;
}

export function encodeCbor(value) {
  const chunks = [];
  encodeCborItem(value, chunks);
  return concatChunks(chunks);
}

function encodeCborItem(value, chunks) {
    if (value instanceof Uint8Array) {
      chunks.push(encodeMajorLength(2, value.length));
      chunks.push(value);
      return;
    }
    if (typeof value === "string") {
      const bytes = textEncoder.encode(value);
      chunks.push(encodeMajorLength(3, bytes.length));
      chunks.push(bytes);
      return;
    }
    if (Array.isArray(value)) {
      chunks.push(encodeMajorLength(4, value.length));
      for (const item of value) {
        encodeCborItem(item, chunks);
      }
      return;
    }
    if (Number.isInteger(value)) {
      if (value >= 0) {
        chunks.push(encodeMajorLength(0, value));
      } else {
        chunks.push(encodeMajorLength(1, -1 - value));
      }
      return;
    }
    if (value === null) {
      chunks.push(Uint8Array.of(0xf6));
      return;
    }
    if (value === true) {
      chunks.push(Uint8Array.of(0xf5));
      return;
    }
    if (value === false) {
      chunks.push(Uint8Array.of(0xf4));
      return;
    }
    throw new Error("unsupported CBOR value");
  }

function encodeMajorLength(major, length) {
    if (!Number.isFinite(length) || length < 0 || Math.floor(length) !== length) {
      throw new Error("invalid CBOR length");
    }
    if (length < 24) {
      return Uint8Array.of((major << 5) | length);
    }
    if (length < 0x100) {
      return Uint8Array.of((major << 5) | 24, length);
    }
    if (length < 0x10000) {
      return Uint8Array.of((major << 5) | 25, (length >> 8) & 0xff, length & 0xff);
    }
    if (length < 0x100000000) {
      return Uint8Array.of(
        (major << 5) | 26,
        (length >>> 24) & 0xff,
        (length >>> 16) & 0xff,
        (length >>> 8) & 0xff,
        length & 0xff
      );
    }
    if (length <= Number.MAX_SAFE_INTEGER) {
      const high = Math.floor(length / 0x100000000);
      const low = length >>> 0;
      return Uint8Array.of(
        (major << 5) | 27,
        (high >>> 24) & 0xff,
        (high >>> 16) & 0xff,
        (high >>> 8) & 0xff,
        high & 0xff,
        (low >>> 24) & 0xff,
        (low >>> 16) & 0xff,
        (low >>> 8) & 0xff,
        low & 0xff
      );
    }
    throw new Error("CBOR length too large");
  }

function concatChunks(chunks) {
    const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const out = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      out.set(chunk, offset);
      offset += chunk.length;
    }
    return out;
  }

function decodeCborItem(bytes, offset) {
    if (offset >= bytes.length) throw new Error("CBOR truncated");
    const first = bytes[offset++];
    const major = first >> 5;
    const addl = first & 0x1f;
    if (major === 7) {
      if (addl === 20) return { value: false, offset };
      if (addl === 21) return { value: true, offset };
      if (addl === 22) return { value: null, offset };
      if (addl === 26) {
        if (offset + 4 > bytes.length) throw new Error("CBOR float truncated");
        const view = new DataView(bytes.buffer, bytes.byteOffset + offset, 4);
        const value = view.getFloat32(0);
        return { value, offset: offset + 4 };
      }
      if (addl === 27) {
        if (offset + 8 > bytes.length) throw new Error("CBOR float truncated");
        const view = new DataView(bytes.buffer, bytes.byteOffset + offset, 8);
        const value = view.getFloat64(0);
        return { value, offset: offset + 8 };
      }
      throw new Error("unsupported CBOR simple value");
    }

    const lengthInfo = readCborLength(bytes, offset, addl);
    const length = lengthInfo.value;
    offset = lengthInfo.offset;
    switch (major) {
      case 0:
        return { value: length, offset };
      case 1:
        return { value: -1 - length, offset };
      case 2: {
        const end = offset + length;
        if (end > bytes.length) throw new Error("CBOR bytes truncated");
        return { value: bytes.slice(offset, end), offset: end };
      }
      case 3: {
        const end = offset + length;
        if (end > bytes.length) throw new Error("CBOR text truncated");
        const text = textDecoder.decode(bytes.slice(offset, end));
        return { value: text, offset: end };
      }
      case 4: {
        const arr = [];
        for (let i = 0; i < length; i += 1) {
          const item = decodeCborItem(bytes, offset);
          arr.push(item.value);
          offset = item.offset;
        }
        return { value: arr, offset };
      }
      case 5: {
        const obj = {};
        for (let i = 0; i < length; i += 1) {
          const keyItem = decodeCborItem(bytes, offset);
          offset = keyItem.offset;
          const valItem = decodeCborItem(bytes, offset);
          offset = valItem.offset;
          obj[String(keyItem.value)] = valItem.value;
        }
        return { value: obj, offset };
      }
      default:
        throw new Error("unsupported CBOR type");
    }
  }

function readCborLength(bytes, offset, addl) {
    if (addl < 24) return { value: addl, offset };
    if (addl === 24) {
      if (offset >= bytes.length) throw new Error("CBOR length truncated");
      return { value: bytes[offset], offset: offset + 1 };
    }
    if (addl === 25) {
      if (offset + 2 > bytes.length) throw new Error("CBOR length truncated");
      const value = (bytes[offset] << 8) | bytes[offset + 1];
      return { value, offset: offset + 2 };
    }
    if (addl === 26) {
      if (offset + 4 > bytes.length) throw new Error("CBOR length truncated");
      const view = new DataView(bytes.buffer, bytes.byteOffset + offset, 4);
      return { value: view.getUint32(0), offset: offset + 4 };
    }
    if (addl === 27) {
      if (offset + 8 > bytes.length) throw new Error("CBOR length truncated");
      const view = new DataView(bytes.buffer, bytes.byteOffset + offset, 8);
      const high = view.getUint32(0);
      const low = view.getUint32(4);
      const value = high * Math.pow(2, 32) + low;
      if (value > Number.MAX_SAFE_INTEGER) throw new Error("CBOR integer too large");
      return { value, offset: offset + 8 };
    }
    throw new Error("indefinite CBOR lengths not supported");
  }
