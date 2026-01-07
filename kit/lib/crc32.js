export function crc32(bytes) {
  let crc = 0xffffffff;
  for (const element of bytes) {
    crc ^= element;
    for (let j = 0; j < 8; j += 1) {
      const mask = -(crc & 1);
      crc = (crc >>> 1) ^ (0xedb88320 & mask);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}
