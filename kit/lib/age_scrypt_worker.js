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

import { scrypt } from "@noble/hashes/scrypt.js";

globalThis.onmessage = (event) => {
  try {
    const { passphrase, labelAndSalt, logN } = event.data ?? {};
    if (
      typeof passphrase !== "string" ||
      !(labelAndSalt instanceof Uint8Array) ||
      !Number.isInteger(logN) ||
      logN < 1 ||
      logN > 20
    ) {
      throw new Error("invalid scrypt worker request");
    }
    const cost = 2 ** logN;
    const key = scrypt(passphrase, labelAndSalt, {
      N: cost,
      r: 8,
      p: 1,
      dkLen: 32,
      maxmem: 128 * 8 * (cost + 2),
    });
    globalThis.postMessage({ key: key }, [key.buffer]);
  } catch (err) {
    globalThis.postMessage({ error: err instanceof Error ? err.message : String(err) });
  }
};
