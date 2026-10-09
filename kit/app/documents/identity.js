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

import { blake2b256 } from "../../lib/blake2b.js";
import { bytesToHex } from "../../lib/bytes.js";
import { DOC_ID_LEN } from "../constants.js";

export function documentIdentityFromDocHash(docHash) {
  const docId = docHash.slice(0, DOC_ID_LEN);
  return {
    docHash,
    docHashHex: bytesToHex(docHash),
    docId,
    docIdHex: bytesToHex(docId),
  };
}

export function documentIdentityFromCiphertext(ciphertext) {
  if (!(ciphertext instanceof Uint8Array)) {
    throw new Error("document ciphertext must be bytes");
  }
  return documentIdentityFromDocHash(blake2b256(ciphertext));
}
