#!/usr/bin/env python3
from __future__ import annotations

import hashlib


def _doc_id_from_ciphertext(ciphertext: bytes) -> bytes:
    return hashlib.blake2b(ciphertext, digest_size=16).digest()


def _doc_hash_from_ciphertext(ciphertext: bytes) -> bytes:
    return hashlib.blake2b(ciphertext, digest_size=32).digest()
